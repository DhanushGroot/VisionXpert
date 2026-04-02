from flask import Flask, render_template, url_for, request
import sqlite3
from A_Recognition import analyse
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/userlog', methods=['GET', 'POST'])
def userlog():
    if request.method == 'POST':

        connection = sqlite3.connect('user_data.db')
        cursor = connection.cursor()

        name = request.form['name']
        password = request.form['password']

        query = "SELECT name, password FROM user WHERE name = '"+name+"' AND password= '"+password+"'"
        cursor.execute(query)

        result = cursor.fetchall()

        if len(result) == 0:
            return render_template('index.html', msg='Sorry, Incorrect Credentials Provided,  Try Again')
        else:
            return render_template('userlog.html')

    return render_template('index.html')


@app.route('/userreg', methods=['GET', 'POST'])
def userreg():
    if request.method == 'POST':

        connection = sqlite3.connect('user_data.db')
        cursor = connection.cursor()

        name = request.form['name']
        password = request.form['password']
        mobile = request.form['phone']
        email = request.form['email']
        
        print(name, mobile, email, password)

        command = """CREATE TABLE IF NOT EXISTS user(name TEXT, password TEXT, mobile TEXT, email TEXT)"""
        cursor.execute(command)

        cursor.execute("INSERT INTO user VALUES ('"+name+"', '"+password+"', '"+mobile+"', '"+email+"')")
        connection.commit()

        return render_template('index.html', msg='Successfully Registered')
    
    return render_template('index.html')

@app.route('/video', methods=['GET', 'POST'])
def video():
    if request.method == 'POST':
        
        fileName=request.form['filename']
        if fileName:
            print(f"readed file {fileName}")
        else:
            return render_template('userlog.html')
        

        analyse('test/'+fileName)
        return render_template('userlog.html')
    return render_template('userlog.html')



@app.route('/Live1', methods=['GET', 'POST'])
def Live1():
    if request.method == 'POST':
        
        fileName=request.form['filename1']
        if fileName:
            print(f"readed file {fileName}")
            
            f = open('temp.txt', 'w')
            f.write('testweapon/'+fileName)
            f.close()
        else:
            f = open('temp.txt', 'w')
            f.write('0')
            f.close()
        
        os.system('python detect1.py')
        return render_template('userlog.html')
    return render_template('userlog.html')


@app.route('/Live2', methods=['GET', 'POST'])
def Live2():
    if request.method == 'POST':
        
        fileName=request.form['filename2']
        if fileName:
            print(f"readed file {fileName}")
            
            f = open('temp.txt', 'w')
            f.write('testaccident/'+fileName)
            f.close()
        else:
            f = open('temp.txt', 'w')
            f.write('0')
            f.close()
        
        os.system('python detect2.py')
        return render_template('userlog.html')
    return render_template('userlog.html')


@app.route('/Live3', methods=['GET', 'POST'])
def Live3():
    if request.method == 'POST':
        
        fileName=request.form['filename3']
        if fileName:
            print(f"readed file {fileName}")
            
            f = open('temp.txt', 'w')
            f.write('testexplosion/'+fileName)
            f.close()
        else:
            f = open('temp.txt', 'w')
            f.write('0')
            f.close()
        
        os.system('python detect3.py')
        return render_template('userlog.html')
    return render_template('userlog.html')



@app.route('/Live4', methods=['GET', 'POST'])
def Live4():
    os.system('python helmet_detection.py')
    return render_template('userlog.html')
  
@app.route('/Live5', methods=['GET', 'POST'])
def Live5():
    os.system('python detect4.py')
    return render_template('userlog.html')
    


@app.route('/Live6', methods=['GET', 'POST'])
def Live6():
    os.system('python detect5.py')
    return render_template('userlog.html')
   
@app.route('/request-demo-page.html')
def request_demo():
    return render_template('request-demo-page.html')
@app.route('/about-us-page.html')
def about_us():
    return render_template('about-us-page.html')

if __name__ == "__main__":

    app.run(debug=True, use_reloader=False)
