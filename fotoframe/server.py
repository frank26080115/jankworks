#!/usr/bin/env python3

import sys, os, io, gc, random, time, datetime, subprocess, glob

from flask import Flask, send_from_directory, send_file

app = Flask(__name__)

@app.route('/')
def index():
    return send_file('index.htm')

@app.route('/js/<path:path>')
def send_js(path):
    return send_from_directory('js', path)

@app.route('/Pictures/<path:path>')
def send_pictures(path):
    return send_from_directory('Pictures', path)

@app.route('/ls')
def list_pictures():
    dir = './Pictures'
    allfiles = []
    allexts  = ('*.jpg', '*.png')
    for ext in allexts:
        allfiles.extend(glob.glob(os.path.join(dir, ext        ), recursive = True))
        allfiles.extend(glob.glob(os.path.join(dir, ext.upper()), recursive = True))
    reply = ''
    for i in allfiles:
        if i.lower() not in reply.lower():
            reply += i + ';'
    return reply

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')