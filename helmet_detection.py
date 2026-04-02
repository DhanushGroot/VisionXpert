import argparse
import csv
import os
import platform
import sys
import time
from pathlib import Path
import telepot
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime
import winsound  # For Windows beep sound
import threading
import queue
import numpy as np
import cv2
import glob
import re

# Keep existing telepot configurations
bot = telepot.Bot('Add your bot token here')
bot2 = telepot.Bot("Add your bot token here")
ch_id = "Add your channel ID here"

FILE = Path(__file__).resolve()
ROOT = FILE.parents[0]  # YOLOv5 root directory
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # add ROOT to PATH
ROOT = Path(os.path.relpath(ROOT, Path.cwd()))  # relative

from myFROZEN_GRAPH_HEAD import FROZEN_GRAPH_HEAD
from tensorflow.keras.models import load_model

# Email configuration
EMAIL_SENDER = "Add your email here"  # Replace with your email
EMAIL_PASSWORD = "Add your email APP password here"    # Replace with your app password (for Gmail)
EMAIL_RECIPIENTS = ["Add your email here"]  # Replace with recipient emails
EMAIL_SUBJECT = "ALERT: No Helmet Detected!"

# Configuration for alert system
MAX_QUEUE_SIZE = 10  # Maximum number of alerts in queue
MIN_ALERT_INTERVAL = 5  # Minimum seconds between alerts


def increment_path(path, exist_ok=False, sep='', mkdir=True):
    """Increment file or directory path, i.e. runs/exp --> runs/exp0, runs/exp1 etc."""
    path = Path(path)  # os-agnostic
    if path.exists() and not exist_ok:
        suffix = path.suffix
        path = path.with_suffix('')
        dirs = glob.glob(f"{path}{sep}*")  # similar paths
        matches = [re.search(rf"%s{sep}(\d+)" % path.stem, d) for d in dirs]
        i = [int(m.groups()[0]) for m in matches if m]  # indices
        n = max(i) + 1 if i else 2  # increment number
        path = Path(f"{path}{sep}{n}{suffix}")  # update path
    dir = path if path.suffix == '' else path.parent  # directory
    if not dir.exists() and mkdir:
        dir.mkdir(parents=True, exist_ok=True)  # make directory
    return path


class AlertManager:
    """
    Manages alerts in a separate thread to prevent blocking the main detection loop
    """
    def __init__(self, email_dir, min_interval=5):
        self.email_dir = email_dir
        self.min_interval = min_interval
        self.last_alert_time = 0
        self.alert_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self.is_running = True
        
        # Start the alert processor thread
        self.alert_thread = threading.Thread(target=self._process_alerts)
        self.alert_thread.daemon = True
        self.alert_thread.start()
    
    def add_alert(self, img, detection_info, confidence):
        """Add a new alert to the queue"""
        try:
            # Don't block if queue is full, just log and continue
            if self.alert_queue.full():
                print("Alert queue is full. Skipping this alert.")
                return False
                
            # Add to queue
            self.alert_queue.put((img.copy(), detection_info, confidence))
            return True
        except Exception as e:
            print(f"Error adding alert to queue: {str(e)}")
            return False
    
    def _process_alerts(self):
        """Process alerts from the queue in a separate thread"""
        while self.is_running:
            try:
                if not self.alert_queue.empty():
                    # Get next alert
                    img, detection_info, confidence = self.alert_queue.get()
                    
                    # Check if it's time for a new alert
                    current_time = time.time()
                    if current_time - self.last_alert_time > self.min_interval:
                        self.last_alert_time = current_time
                        
                        # Save image for email
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        email_img_path = str(self.email_dir / f"no_helmet_{timestamp}.jpg")
                        cv2.imwrite(email_img_path, img)
                        
                        # Start parallel tasks for notifications
                        tasks = []
                        
                        # Sound alert thread
                        sound_thread = threading.Thread(target=self._play_alarm_sound)
                        sound_thread.daemon = True
                        tasks.append(sound_thread)
                        
                        # Telegram alert thread
                        telegram_thread = threading.Thread(
                            target=self._send_telegram_alert, 
                            args=(detection_info, confidence)
                        )
                        telegram_thread.daemon = True
                        tasks.append(telegram_thread)
                        
                        # Email alert thread
                        email_thread = threading.Thread(
                            target=self._send_email_alert, 
                            args=(email_img_path, detection_info)
                        )
                        email_thread.daemon = True
                        tasks.append(email_thread)
                        
                        # Start all notification tasks
                        for task in tasks:
                            task.start()
                    
                    # Mark task as done
                    self.alert_queue.task_done()
                else:
                    # Sleep to prevent CPU spinning
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f"Error processing alert: {str(e)}")
                time.sleep(0.5)  # Sleep to prevent rapid error loops
    
    def _play_alarm_sound(self):
        """Play alarm beep sound when detection occurs"""
        try:
            # For Windows systems
            if platform.system() == 'Windows':
                # Beep at 750 Hz for 500 milliseconds
                for _ in range(2):  # Reduced to 2 beeps to be less intrusive
                    winsound.Beep(750, 500)
                    winsound.Beep(950, 500)
            # For Linux/Unix systems
            elif platform.system() == 'Linux' or platform.system() == 'Darwin':
                for _ in range(2):  # Reduced to 2 beeps
                    os.system('play -nq -t alsa synth 0.5 sine 750')
                    os.system('play -nq -t alsa synth 0.5 sine 950')
        except Exception as e:
            print(f"Failed to play alarm sound: {str(e)}")
    
    def _send_telegram_alert(self, detection_info, confidence):
        """Send Telegram alert"""
        try:
            alert_message = f"No Helmet detected with confidence {confidence:.2f}"
            bot.sendMessage('7235308955', alert_message)
            bot2.sendMessage(ch_id, alert_message)
            print("Telegram alert sent successfully")
        except Exception as e:
            print(f"Failed to send Telegram alert: {str(e)}")
    
    def _send_email_alert(self, image_path, detection_info):
        """Send email with the detected no-helmet image"""
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = EMAIL_SENDER
            msg['To'] = ", ".join(EMAIL_RECIPIENTS)
            msg['Subject'] = EMAIL_SUBJECT
            
            # Email body
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            body = f"""
            NO HELMET DETECTION ALERT!
            
            Time: {timestamp}
            
            Detection Information:
            {detection_info}
            
            This is an automated alert. Please take appropriate action immediately.
            """
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach the image
            with open(image_path, 'rb') as img_file:
                img_data = img_file.read()
                image = MIMEImage(img_data, name=os.path.basename(image_path))
                msg.attach(image)
            
            # Connect to the SMTP server
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)
            
            print(f"Email alert sent to {', '.join(EMAIL_RECIPIENTS)}")
            return True
        
        except Exception as e:
            print(f"Failed to send email: {str(e)}")
            return False
    
    def shutdown(self):
        """Shutdown the alert manager"""
        self.is_running = False
        if self.alert_thread.is_alive():
            self.alert_thread.join(timeout=1.0)


class HelmetDetector:
    """Class to handle helmet detection"""
    def __init__(self, helmet_model_path, head_detection_pb):
        self.helmet_model = load_model(helmet_model_path)
        print("Helmet model loaded")
        
        self.head_detector = FROZEN_GRAPH_HEAD(head_detection_pb)
        print("Head model loaded")
    
    def detect_helmet(self, img):
        """Check if helmet is present in the image"""
        try:
            img_resized = cv2.resize(img, (224, 224))
            img_array = np.array(img_resized, dtype='float32')
            img_array = img_array.reshape(1, 224, 224, 3)
            img_array = img_array / 255.0
            prediction = int(self.helmet_model.predict(img_array)[0][0])
            
            # 0 = helmet, 1 = no-helmet (based on original code)
            return prediction
        except Exception as e:
            print(f"Error detecting helmet: {str(e)}")
            return 1  # Default to "no helmet" in case of error
    
    def detect_heads(self, img):
        """Detect heads in the image"""
        try:
            im_height, im_width, im_channel = img.shape
            boxes, scores, classes, num_detections = self.head_detector.run(img, im_height, im_width)
            boxes = np.squeeze(boxes)
            scores = np.squeeze(scores)

            head_count = 0
            coords = []
            for score, box in zip(scores, boxes):
                if score > 0.15:  # Confidence threshold from original code
                    head_count += 1
                    left = int(box[1] * im_width)
                    top = int(box[0] * im_height)
                    right = int(box[3] * im_width)
                    bottom = int(box[2] * im_height)
                    coords.append([left, top, right, bottom])
            return head_count, coords
        except Exception as e:
            print(f"Error detecting heads: {str(e)}")
            return 0, []


def run(
    helmet_model_path="helmet_detection.h5",
    head_detection_pb="head_detection.pb",
    source=0,  # 0 is default webcam
    view_img=True,  # Default to True to ensure the window shows
    save_img=True,
    save_txt=False,
    save_csv=False,
    project=ROOT / "runs/helmet_detect",
    name="exp",
    exist_ok=False,
    line_thickness=2,
    conf_thres=0.15,  # Confidence threshold for head detection
    hide_conf=False,
    min_alert_interval=5,  # Minimum seconds between alerts
):
    # Convert source to proper format
    source = str(source)
    is_file = os.path.isfile(source)
    is_url = source.lower().startswith(("rtsp://", "rtmp://", "http://", "https://"))
    webcam = source.isnumeric() or source.endswith(".streams") or (is_url and not is_file)
    
    # Directories
    save_dir = increment_path(Path(project) / name, exist_ok=exist_ok)  # increment run
    (save_dir / "labels" if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

    # Create a directory for email screenshots
    email_screenshots_dir = save_dir / "email_screenshots"
    email_screenshots_dir.mkdir(exist_ok=True)

    # Initialize the alert manager
    alert_manager = AlertManager(email_screenshots_dir, min_interval=min_alert_interval)
    
    try:
        # Initialize detector
        detector = HelmetDetector(helmet_model_path, head_detection_pb)
        
        # Initialize video capture
        if webcam:
            print(f"Attempting to open webcam {source}...")
            cap = cv2.VideoCapture(int(source))
            # Explicitly set camera properties to ensure it works
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            print(f"Webcam opened: {cap.isOpened()}")
        else:
            cap = cv2.VideoCapture(source)
            print(f"Reading from source: {source}")
        
        # Check if camera opened successfully
        if not cap.isOpened():
            print("Error: Could not open video source.")
            return
        
        # Get video properties for saving
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        if fps == 0:  # Default to 30 if not available
            fps = 30
            
        print(f"Video dimensions: {width}x{height}, FPS: {fps}")
        
        # Video writer setup
        vid_writer = None
        if save_img and not webcam:  # Only save video for non-webcam sources
            save_path = str(save_dir / "output.mp4")
            vid_writer = cv2.VideoWriter(
                save_path, 
                cv2.VideoWriter_fourcc(*"mp4v"), 
                fps, 
                (width, height)
            )
        
        # CSV file setup
        if save_csv:
            csv_path = save_dir / "detections.csv"
            csv_header = ["Timestamp", "Head Count", "With Helmet", "Without Helmet"]
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(csv_header)
        
        # Create and name window before entering the loop
        if view_img:
            cv2.namedWindow("Helmet Detection", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Helmet Detection", width, height)
            print("Display window created")
        
        print("Starting detection...")
        frame_count = 0
        
        while True:
            # Read frame
            ret, frame = cap.read()
            
            if not ret:
                print("Failed to receive frame. Exiting...")
                break
                
            frame_count += 1
            if frame_count % 30 == 0:  # Log every 30 frames
                print(f"Processing frame {frame_count}")
            
            # Make a copy for annotations
            annotated_frame = frame.copy()
            
            # Detect heads
            head_count, head_coords = detector.detect_heads(frame)
            
            # Statistics for this frame
            helmet_count = 0
            no_helmet_count = 0
            
            # Process each detected head
            for i, head_box in enumerate(head_coords):
                left, top, right, bottom = head_box
                
                # Extract head region
                if left >= 0 and top >= 0 and right < frame.shape[1] and bottom < frame.shape[0]:
                    head_img = frame[top:bottom, left:right]
                    
                    # Skip if head region is too small
                    if head_img.size == 0 or head_img.shape[0] < 10 or head_img.shape[1] < 10:
                        continue
                    
                    # Detect helmet
                    helmet_result = detector.detect_helmet(head_img)
                    
                    # Update counts
                    if helmet_result == 0:  # Helmet detected
                        helmet_count += 1
                        label = "Helmet"
                        color = (0, 255, 0)  # Green for helmet
                    else:  # No helmet
                        no_helmet_count += 1
                        label = "No Helmet"
                        color = (0, 0, 255)  # Red for no helmet
                        
                        # Send alert for no helmet
                        detection_info = f"Person {i+1} without helmet detected"
                        confidence = 0.95  # Placeholder confidence
                        alert_manager.add_alert(annotated_frame, detection_info, confidence)
                    
                    # Draw bounding box
                    cv2.rectangle(annotated_frame, (left, top), (right, bottom), color, line_thickness)
                    
                    # Add label
                    if not hide_conf:
                        conf_label = f"{label}"
                        cv2.putText(
                            annotated_frame, 
                            conf_label, 
                            (left, top - 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 
                            0.5, 
                            color, 
                            line_thickness // 2
                        )
            
            # Add overall statistics to frame
            stats_text = f"Heads: {head_count} | With Helmet: {helmet_count} | No Helmet: {no_helmet_count}"
            cv2.putText(
                annotated_frame,
                stats_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )
            
            # Display result
            if view_img:
                try:
                    print("Attempting to show frame...") if frame_count == 1 else None
                    cv2.imshow("Helmet Detection", annotated_frame)
                    print("Frame displayed successfully") if frame_count == 1 else None
                    
                    # Break loop on 'q' key press - using a longer waitKey to ensure UI updates
                    key = cv2.waitKey(30) & 0xFF
                    if key == ord('q'):
                        print("Q key pressed. Exiting...")
                        break
                except Exception as e:
                    print(f"Error displaying frame: {str(e)}")
            
            # Save frame/video
            if save_img:
                if webcam:  # Save individual frames from webcam
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    if no_helmet_count > 0:  # Only save frames with violations
                        save_path = str(save_dir / f"no_helmet_{timestamp}.jpg")
                        cv2.imwrite(save_path, annotated_frame)
                elif vid_writer is not None:
                    vid_writer.write(annotated_frame)
            
            # Save to CSV
            if save_csv:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(csv_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp, head_count, helmet_count, no_helmet_count])
        
        # Release resources
        cap.release()
        if vid_writer is not None:
            vid_writer.release()
        cv2.destroyAllWindows()
        
    except Exception as e:
        print(f"Error in detection loop: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Ensure we properly shutdown the alert manager
        alert_manager.shutdown()
        
        # Make sure to release resources even if exception occurred
        try:
            cap.release()
        except:
            pass
        try:
            if vid_writer is not None:
                vid_writer.release()
        except:
            pass
        cv2.destroyAllWindows()


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--helmet-model-path', type=str, default='helmet_detection.h5', help='helmet detection model path')
    parser.add_argument('--head-detection-pb', type=str, default='head_detection.pb', help='head detection model path')
    parser.add_argument('--source', type=str, default='0', help='file/dir/URL/glob, 0 for webcam')
    parser.add_argument('--view-img', action='store_true', help='show results')
    parser.add_argument('--save-img', action='store_true', help='save results')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--save-csv', action='store_true', help='save results to CSV')
    parser.add_argument('--project', default=ROOT / 'runs/helmet_detect', help='save results to project/name')
    parser.add_argument('--name', default='exp', help='save results to project/name')
    parser.add_argument('--exist-ok', action='store_true', help='existing project/name ok, do not increment')
    parser.add_argument('--line-thickness', default=2, type=int, help='bounding box thickness (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.15, help='confidence threshold')
    parser.add_argument('--hide-conf', action='store_true', help='hide confidences')
    parser.add_argument('--min-alert-interval', type=int, default=5, help='minimum seconds between alerts')
    opt = parser.parse_args()
    return opt


def main():
    opt = parse_opt()
    print(f"Starting with options: {vars(opt)}")
    
    # Force view_img to True to ensure window is displayed
    if not opt.view_img:
        print("Note: --view-img flag not provided. Enabling display window by default.")
        opt.view_img = True
        
    try:
        # Match parameter names between parse_opt and run function
        run(
            helmet_model_path=opt.helmet_model_path,
            head_detection_pb=opt.head_detection_pb,
            source=opt.source,
            view_img=opt.view_img,
            save_img=opt.save_img,
            save_txt=opt.save_txt,
            save_csv=opt.save_csv,
            project=opt.project,
            name=opt.name,
            exist_ok=opt.exist_ok,
            line_thickness=opt.line_thickness,
            conf_thres=opt.conf_thres,
            hide_conf=opt.hide_conf,
            min_alert_interval=opt.min_alert_interval
        )
    except Exception as e:
        print(f"Error in main function: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Simple test for camera display
    test_camera = False
    if test_camera:
        print("Running camera test...")
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("ERROR: Could not open camera!")
            else:
                print("Camera opened successfully. Showing test window.")
                cv2.namedWindow("Camera Test", cv2.WINDOW_NORMAL)
                while True:
                    ret, frame = cap.read()
                    if ret:
                        cv2.imshow("Camera Test", frame)
                        if cv2.waitKey(30) & 0xFF == ord('q'):
                            break
                    else:
                        print("Failed to get frame")
                        break
                cap.release()
                cv2.destroyAllWindows()
        except Exception as e:
            print(f"Camera test failed: {str(e)}")
    
    # Run the main program
    main()