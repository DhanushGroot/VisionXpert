import argparse
import csv
import os
import platform
import sys
import threading
import time
from pathlib import Path
from queue import Queue
import telepot
from datetime import datetime

# Import sound libraries but use them in threads
if platform.system() == 'Windows':
    import winsound
else:
    import subprocess

# Set up Telegram bots
bot = telepot.Bot('Add your bot token here')
bot2 = telepot.Bot("Add your bot token here")
ch_id = "Add your channel ID here"

# Fix for Windows path issues
import pathlib
temp = pathlib.PosixPath
pathlib.PosixPath = pathlib.WindowsPath

# Add email libraries
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import torch

FILE = Path(__file__).resolve()
ROOT = FILE.parents[0]  # YOLOv5 root directory
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # add ROOT to PATH
ROOT = Path(os.path.relpath(ROOT, Path.cwd()))  # relative

from ultralytics.utils.plotting import Annotator, colors, save_one_box

from models.common import DetectMultiBackend
from utils.dataloaders import IMG_FORMATS, VID_FORMATS, LoadImages, LoadScreenshots, LoadStreams
from utils.general import (
    LOGGER,
    Profile,
    check_file,
    check_img_size,
    check_imshow,
    check_requirements,
    colorstr,
    cv2,
    increment_path,
    non_max_suppression,
    print_args,
    scale_boxes,
    strip_optimizer,
    xyxy2xywh,
)
from utils.torch_utils import select_device, smart_inference_mode

# Create alert queues and cooldown tracking
alert_queue = Queue()
telegram_queue = Queue()
email_queue = Queue()
last_alert_time = 0
ALERT_COOLDOWN = 5  # seconds between alerts

# Thread-safe flag to control when to exit
exit_flag = threading.Event()

# Play alarm in a separate thread
def play_alarm_thread():
    """Thread function to play alarm sounds without blocking main detection loop"""
    try:
        if platform.system() == 'Windows':
            # On Windows, use winsound to play the alarm
            winsound.Beep(2500, 500)  # shorter beep, less blocking
        elif platform.system() == 'Darwin':  # macOS
            # On macOS, use afplay
            subprocess.Popen(['afplay', '/System/Library/Sounds/Sosumi.aiff'], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif platform.system() == 'Linux':
            # On Linux, use paplay or aplay if available
            try:
                subprocess.Popen(['paplay', '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                try:
                    subprocess.Popen(['aplay', '-q', '/usr/share/sounds/alsa/Front_Center.wav'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    print('\a')  # ASCII Bell character
    except Exception as e:
        LOGGER.error(f"Failed to play alarm sound: {e}")

# Worker thread for playing alarm sounds
def alarm_worker():
    while not exit_flag.is_set():
        try:
            # Wait for an alert to be queued (timeout allows checking exit_flag)
            if alert_queue.get(timeout=1):
                play_alarm_thread()
                alert_queue.task_done()
        except:
            pass  # Queue.Empty exception when timeout occurs

# Telegram message worker thread
def telegram_worker():
    while not exit_flag.is_set():
        try:
            # Get message from queue with timeout
            message = telegram_queue.get(timeout=1)
            if message:
                try:
                    bot.sendMessage('7235308955', message)
                    bot2.sendMessage(ch_id, message)
                except Exception as e:
                    LOGGER.error(f"Telegram error: {e}")
                telegram_queue.task_done()
        except:
            pass  # Queue.Empty exception when timeout occurs

# Email worker thread function
def email_worker():
    while not exit_flag.is_set():
        try:
            # Get email params from queue with timeout
            image_path = email_queue.get(timeout=1)
            if image_path:
                try:
                    # Email configuration
                    sender_email = "Add your email here"
                    receiver_email = "Add your email here"
                    password = "Add your email APP password here"

                    # Create message
                    msg = MIMEMultipart()
                    msg['Subject'] = "Accident Detected"
                    msg['From'] = sender_email
                    msg['To'] = receiver_email
                    
                    # Add message body
                    body = f"An accident was detected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
                    msg.attach(MIMEText(body, 'plain'))
                    
                    # Attach image
                    try:
                        with open(image_path, 'rb') as img_file:
                            img_data = img_file.read()
                            image = MIMEImage(img_data)
                            image.add_header('Content-Disposition', 'attachment', filename=os.path.basename(image_path))
                            msg.attach(image)
                    except FileNotFoundError:
                        LOGGER.error(f"Could not find the image file {image_path} for email attachment")
                        msg.attach(MIMEText("Image file could not be attached.", 'plain'))
                    
                    # Connect to server and send email
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
                        server.login(sender_email, password)
                        server.sendmail(sender_email, receiver_email, msg.as_string())
                    LOGGER.info(f"Email alert sent with image: {image_path}")
                except Exception as e:
                    LOGGER.error(f"Failed to send email: {e}")
                email_queue.task_done()
        except:
            pass  # Queue.Empty exception when timeout occurs

# Trigger alert with cooldown mechanism
def trigger_alert(image_path=None):
    global last_alert_time
    current_time = time.time()
    
    # Check if we're still in cooldown period
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return False
    
    # Update last alert time
    last_alert_time = current_time
    
    # Queue alerts
    alert_queue.put(True)
    telegram_queue.put("Accident detected")
    
    if image_path:
        email_queue.put(image_path)
    
    return True

@smart_inference_mode()
def run(
    weights=ROOT / "yolov5s.pt",  # model path or triton URL
    source=ROOT / "data/images",  # file/dir/URL/glob/screen/0(webcam)
    data=ROOT / "data/coco128.yaml",  # dataset.yaml path
    imgsz=(640, 640),  # inference size (height, width)
    conf_thres=0.25,  # confidence threshold
    iou_thres=0.45,  # NMS IOU threshold
    max_det=1000,  # maximum detections per image
    device="",  # cuda device, i.e. 0 or 0,1,2,3 or cpu
    view_img=True,  # show results
    save_txt=False,  # save results to *.txt
    save_csv=False,  # save results in CSV format
    save_conf=False,  # save confidences in --save-txt labels
    save_crop=False,  # save cropped prediction boxes
    nosave=False,  # do not save images/videos
    classes=None,  # filter by class: --class 0, or --class 0 2 3
    agnostic_nms=False,  # class-agnostic NMS
    augment=False,  # augmented inference
    visualize=False,  # visualize features
    update=False,  # update all models
    project=ROOT / "runs/detect",  # save results to project/name
    name="exp",  # save results to project/name
    exist_ok=False,  # existing project/name ok, do not increment
    line_thickness=3,  # bounding box thickness (pixels)
    hide_labels=False,  # hide labels
    hide_conf=False,  # hide confidences
    half=False,  # use FP16 half-precision inference
    dnn=False,  # use OpenCV DNN for ONNX inference
    vid_stride=1,  # video frame-rate stride
):
    # Start worker threads
    threading.Thread(target=alarm_worker, daemon=True).start()
    threading.Thread(target=telegram_worker, daemon=True).start()
    threading.Thread(target=email_worker, daemon=True).start()
    
    source = str(source)
    save_img = not nosave and not source.endswith(".txt")  # save inference images
    is_file = Path(source).suffix[1:] in (IMG_FORMATS + VID_FORMATS)
    is_url = source.lower().startswith(("rtsp://", "rtmp://", "http://", "https://"))
    webcam = source.isnumeric() or source.endswith(".streams") or (is_url and not is_file)
    screenshot = source.lower().startswith("screen")
    if is_url and is_file:
        source = check_file(source)  # download

    # Directories
    save_dir = increment_path(Path(project) / name, exist_ok=exist_ok)  # increment run
    (save_dir / "labels" if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

    # Create alerts directory for accident detection images
    alerts_dir = save_dir / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    device = select_device(device)
    model = DetectMultiBackend(weights, device=device, dnn=dnn, data=data, fp16=half)
    stride, names, pt = model.stride, model.names, model.pt
    imgsz = check_img_size(imgsz, s=stride)  # check image size

    # Dataloader
    bs = 1  # batch_size
    if webcam:
        view_img = check_imshow(warn=True)
        dataset = LoadStreams(source, img_size=imgsz, stride=stride, auto=pt, vid_stride=vid_stride)
        bs = len(dataset)
    elif screenshot:
        dataset = LoadScreenshots(source, img_size=imgsz, stride=stride, auto=pt)
    else:
        dataset = LoadImages(source, img_size=imgsz, stride=stride, auto=pt, vid_stride=vid_stride)
    vid_path, vid_writer = [None] * bs, [None] * bs

    # Optimization for webcam: reduce processing for some frames
    frame_count = 0
    process_every = 2  # Process every Nth frame for smoother performance
    
    # Run inference
    model.warmup(imgsz=(1 if pt or model.triton else bs, 3, *imgsz))  # warmup
    seen, windows, dt = 0, [], (Profile(device=device), Profile(device=device), Profile(device=device))
    try:
        for path, im, im0s, vid_cap, s in dataset:
            frame_count += 1
            
            # Skip some frames in webcam mode for better performance
            if webcam and frame_count % process_every != 0:
                continue
                
            with dt[0]:
                im = torch.from_numpy(im).to(model.device)
                im = im.half() if model.fp16 else im.float()  # uint8 to fp16/32
                im /= 255  # 0 - 255 to 0.0 - 1.0
                if len(im.shape) == 3:
                    im = im[None]  # expand for batch dim
                if model.xml and im.shape[0] > 1:
                    ims = torch.chunk(im, im.shape[0], 0)

            # Inference
            with dt[1]:
                visualize = increment_path(save_dir / Path(path).stem, mkdir=True) if visualize else False
                if model.xml and im.shape[0] > 1:
                    pred = None
                    for image in ims:
                        if pred is None:
                            pred = model(image, augment=augment, visualize=visualize).unsqueeze(0)
                        else:
                            pred = torch.cat((pred, model(image, augment=augment, visualize=visualize).unsqueeze(0)), dim=0)
                    pred = [pred, None]
                else:
                    pred = model(im, augment=augment, visualize=visualize)
            # NMS
            with dt[2]:
                pred = non_max_suppression(pred, conf_thres, iou_thres, classes, agnostic_nms, max_det=max_det)

            # Define the path for the CSV file
            csv_path = save_dir / "predictions.csv"

            # Create or append to the CSV file (moved outside the loop for performance)
            def write_to_csv(image_name, prediction, confidence):
                data = {"Image Name": image_name, "Prediction": prediction, "Confidence": confidence}
                with open(csv_path, mode="a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=data.keys())
                    if not csv_path.is_file():
                        writer.writeheader()
                    writer.writerow(data)

            # Process predictions
            for i, det in enumerate(pred):  # per image
                seen += 1

                if webcam:  # batch_size >= 1
                    p, im0, frame = path[i], im0s[i].copy(), dataset.count
                    s += f"{i}: "
                else:
                    p, im0, frame = path, im0s.copy(), getattr(dataset, "frame", 0)

                p = Path(p)  # to Path
                save_path = str(save_dir / p.name)  # im.jpg
                txt_path = str(save_dir / "labels" / p.stem) + ("" if dataset.mode == "image" else f"_{frame}")  # im.txt
                s += "%gx%g " % im.shape[2:]  # print string
                gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
                imc = im0.copy() if save_crop else im0  # for save_crop
                annotator = Annotator(im0, line_width=line_thickness, example=str(names))
                
                accident_detected = False
                
                if len(det):
                    # Rescale boxes from img_size to im0 size
                    det[:, :4] = scale_boxes(im.shape[2:], det[:, :4], im0.shape).round()

                    # Print results
                    for c in det[:, 5].unique():
                        n = (det[:, 5] == c).sum()  # detections per class
                        s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string

                    # Write results
                    for *xyxy, conf, cls in reversed(det):
                        c = int(cls)  # integer class
                        label = names[c] if hide_conf else f"{names[c]}"
                        confidence = float(conf)
                        confidence_str = f"{confidence:.2f}"

                        if save_csv:
                            # Instead of writing to CSV in the detection loop, collect data and write later
                            write_to_csv(p.name, label, confidence_str)

                        if save_txt:  # Write to file
                            xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                            line = (cls, *xywh, conf) if save_conf else (cls, *xywh)  # label format
                            with open(f"{txt_path}.txt", "a") as f:
                                f.write(("%g " * len(line)).rstrip() % line + "\n")

                        if save_img or save_crop or view_img:  # Add bbox to image
                            c = int(cls)  # integer class
                            label = None if hide_labels else (names[c] if hide_conf else f"{names[c]} {conf:.2f}")
                            annotator.box_label(xyxy, label, color=colors(c, True))
                            
                            # Check if the detected object is an accident
                            accident_detected = True
                        
                        if save_crop:
                            save_one_box(xyxy, imc, file=save_dir / "crops" / names[c] / f"{p.stem}.jpg", BGR=True)

                # Stream results
                im0 = annotator.result()
                if view_img:
                    if platform.system() == "Linux" and p not in windows:
                        windows.append(p)
                        cv2.namedWindow(str(p), cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)  # allow window resize (Linux)
                        cv2.resizeWindow(str(p), im0.shape[1], im0.shape[0])
                    cv2.imshow(str(p), im0)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        raise StopIteration  # Exit the loop if 'q' is pressed

                # Handle accident detection with cooldown to prevent alert spam
                if accident_detected:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    alert_path = str(alerts_dir / f"accident_alert_{timestamp}.jpg")
                    
                    # Save alert image in a separate thread
                    def save_alert_image(img, path):
                        cv2.imwrite(path, img)
                        LOGGER.info(f"Accident alert image saved to {path}")
                        
                    # Only trigger alerts with cooldown
                    if trigger_alert(alert_path):
                        # First save the image before adding it to the email queue
                        cv2.imwrite(alert_path, im0)
                        LOGGER.info(f"Accident alert image saved to {alert_path}")
                        
                        # Now put the path in the queue for email sending
                        alert_queue.put(True)
                        telegram_queue.put("Accident detected")
                        email_queue.put(alert_path)
                        LOGGER.info(f"Alert triggered - image path added to email queue: {alert_path}")

                # Save results (image with detections)
                if save_img:
                    if dataset.mode == "image":
                        cv2.imwrite(save_path, im0)
                    else:  # 'video' or 'stream'
                        if vid_path[i] != save_path:  # new video
                            vid_path[i] = save_path
                            if isinstance(vid_writer[i], cv2.VideoWriter):
                                vid_writer[i].release()  # release previous video writer
                            if vid_cap:  # video
                                fps = vid_cap.get(cv2.CAP_PROP_FPS)
                                w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                                h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            else:  # stream
                                fps, w, h = 30, im0.shape[1], im0.shape[0]
                            save_path = str(Path(save_path).with_suffix(".mp4"))  # force *.mp4 suffix on results videos
                            vid_writer[i] = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                        vid_writer[i].write(im0)

            # Print time (inference-only)
            LOGGER.info(f"{s}{'' if len(det) else '(no detections), '}{dt[1].dt * 1E3:.1f}ms")
            
    except (KeyboardInterrupt, StopIteration):
        LOGGER.info("Detection stopped")
    finally:
        # Set exit flag for all worker threads
        exit_flag.set()
        
        # Cleanup resources
        if isinstance(vid_writer, list):
            for writer in vid_writer:
                if writer:
                    writer.release()
        cv2.destroyAllWindows()

    # Print results
    t = tuple(x.t / seen * 1e3 for x in dt)  # speeds per image
    LOGGER.info(f"Speed: %.1fms pre-process, %.1fms inference, %.1fms NMS per image at shape {(1, 3, *imgsz)}" % t)
    if save_txt or save_img:
        s = f"\n{len(list(save_dir.glob('labels/*.txt')))} labels saved to {save_dir / 'labels'}" if save_txt else ""
        LOGGER.info(f"Results saved to {colorstr('bold', save_dir)}{s}")
    if update:
        strip_optimizer(weights[0])  # update model (to fix SourceChangeWarning)


def parse_opt(File):
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", nargs="+", type=str, default=ROOT / "ACCIDENT.pt", help="model path or triton URL")
    parser.add_argument("--source", type=str, default=File, help="file/dir/URL/glob/screen/0(webcam)")
    parser.add_argument("--data", type=str, default=ROOT / "data/coco128.yaml", help="(optional) dataset.yaml path")
    parser.add_argument("--imgsz", "--img", "--img-size", nargs="+", type=int, default=[640], help="inference size h,w")
    parser.add_argument("--conf-thres", type=float, default=0.45, help="confidence threshold")
    parser.add_argument("--iou-thres", type=float, default=0.45, help="NMS IoU threshold")
    parser.add_argument("--max-det", type=int, default=1000, help="maximum detections per image")
    parser.add_argument("--device", default="", help="cuda device, i.e. 0 or 0,1,2,3 or cpu")
    parser.add_argument("--view-img", action="store_true", help="show results")
    parser.add_argument("--save-txt", action="store_true", help="save results to *.txt")
    parser.add_argument("--save-csv", action="store_true", help="save results in CSV format")
    parser.add_argument("--save-conf", action="store_true", help="save confidences in --save-txt labels")
    parser.add_argument("--save-crop", action="store_true", help="save cropped prediction boxes")
    parser.add_argument("--nosave", action="store_true", help="do not save images/videos")
    parser.add_argument("--classes", nargs="+", type=int, help="filter by class: --classes 0, or --classes 0 2 3")
    parser.add_argument("--agnostic-nms", action="store_true", help="class-agnostic NMS")
    parser.add_argument("--augment", action="store_true", help="augmented inference")
    parser.add_argument("--visualize", action="store_true", help="visualize features")
    parser.add_argument("--update", action="store_true", help="update all models")
    parser.add_argument("--project", default=ROOT / "runs/detect", help="save results to project/name")
    parser.add_argument("--name", default="exp", help="save results to project/name")
    parser.add_argument("--exist-ok", action="store_true", help="existing project/name ok, do not increment")
    parser.add_argument("--line-thickness", default=3, type=int, help="bounding box thickness (pixels)")
    parser.add_argument("--hide-labels", default=False, action="store_true", help="hide labels")
    parser.add_argument("--hide-conf", default=False, action="store_true", help="hide confidences")
    parser.add_argument("--half", action="store_true", help="use FP16 half-precision inference")
    parser.add_argument("--dnn", action="store_true", help="use OpenCV DNN for ONNX inference")
    parser.add_argument("--vid-stride", type=int, default=1, help="video frame-rate stride")
    opt = parser.parse_args()
    opt.imgsz *= 2 if len(opt.imgsz) == 1 else 1  # expand
    print_args(vars(opt))
    return opt


def main(opt):
    check_requirements(ROOT / "requirements.txt", exclude=("tensorboard", "thop"))
    run(**vars(opt))


if __name__ == "__main__":
    f = open('temp.txt', 'r')
    File = f.read()
    f.close()
    opt = parse_opt(File)
    main(opt)