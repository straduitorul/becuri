#!/usr/bin/env python3
import cherrypy
import hashlib
import os
import queue
import random
import re
import struct
import threading
import time
import zlib

from cherrypy.lib import auth_digest

import neopixel
import board

comm_sem = threading.Semaphore()
comm = {
    'running': True,
    'shutdown': False,
    'main': {
        'playing': ''
    },
    'test': {
        'testing': False,
        'username': '',
        'filename': ''
    }
}

class Controller(threading.Thread):
    def __init__(self):
        # Pixels variables
        self.npx = 50
        self.pixels = neopixel.NeoPixel(board.D18, self.npx, brightness=1.0, auto_write=False, pixel_order=neopixel.RGB)

        # Main animations variables
        self.anims = []
        self.anim_index = 0
        self.anim_data = b''
        self.anim_offset = 0
        self.init_main_animation()

        # Testing animations variables
        self.test_data = b''
        self.test_offset = 0

        # Other variables
        self.conf = None
        
        self.anim_startup()

        threading.Thread.__init__(self)

    def run(self):
        while True:
            global comm
            comm_sem.acquire()
            self.conf = comm.copy()
            comm_sem.release()

            # Check if we should show anything
            if not self.conf['running']:
                time.sleep(1)
                continue

            # Check if we should shutdown
            if self.conf['shutdown']:
                self.anim_shutdown()
                return

            if self.conf['test']['filename'] != '':
                # Load test file
                self.test_data = zlib.decompress(open(os.path.join(os.getcwd(), 'temp', self.conf['test']['filename']), 'rb').read())
                self.test_offset = 0
                comm_sem.acquire()
                comm['test']['testing'] = True
                comm['test']['filename'] = ''
                self.conf = comm.copy()
                comm_sem.release()
            
            if self.conf['test']['testing']:
                self.run_test_animation()
            else:
                self.run_main_animation()

    def update_now_playing(self):
        comm_sem.acquire()
        global comm
        comm['main']['playing'] = self.anims[self.anim_index]
        comm_sem.release()

    def init_main_animation(self):
        dpath = os.path.join(os.getcwd(), 'animations')
        self.anims = [f for f in os.listdir(dpath) if os.path.isfile(os.path.join(dpath, f))]
        if len(self.anims) == 0:
            raise IndexError
        random.shuffle(self.anims)
        self.anim_index = 0
        print('Loading %s' % os.path.join(dpath, self.anims[self.anim_index]))
        self.anim_data = zlib.decompress(open(os.path.join(dpath, self.anims[self.anim_index]), 'rb').read())
        # TODO: only accept valid zlib files
        self.anim_offset = 0
        self.update_now_playing()

    def run_main_animation(self):
        for i in range(100):
            self.update_lights(self.anim_data, self.anim_offset)
            self.anim_offset += 4
            if self.anim_offset >= len(self.anim_data):
                self.anim_offset = 0
                self.anim_index += 1 # TODO: bug: when anim is over it does not load the other animation
                if self.anim_index >= len(self.anims):
                    self.anim_index = 0
                self.update_now_playing()

    def run_test_animation(self):
        for i in range(100):
            self.update_lights(self.test_data, self.test_offset)
            self.test_offset += 4
            if self.test_offset >= len(self.test_data):
                # TODO: add exit animation
                comm_sem.acquire()
                global comm
                comm['test']['testing'] = False
                comm_sem.release()
                break


    def update_lights(self, data, offset):
        bdata = struct.unpack_from('>I', data, offset)[0]
        cmd = bdata >> 24
        if bdata == 0xdeadbeef:
            # print('commit')
            self.pixels.show()
        elif cmd == 0xd0:
            # print('sleep')
            time.sleep(1 if (bdata & 0xffffff) > 1000 else (bdata & 0xffffff) / 1000)
        else:
            r = bdata >> 16 & 0xff
            g = bdata >> 8 & 0xff
            b = bdata & 0xff
            if cmd == 0xf0:
                # print('pixels.fill((%d, %d, %d))' % (r, g, b))
                self.pixels.fill((r, g, b))
            elif cmd < self.npx:
                # print('pixels[%d] = (%d, %d, %d)' % (cmd, r, g, b))
                self.pixels[cmd] = (r, g, b)

    ##############
    # ANIMATIONS #
    ##############
    def anim_startup(self):
        def pushpx(i):
            self.pixels.fill((0, 0, 0))
            for j in range(i):
                self.pixels[j] = (0, 255, 0)
            self.pixels.show()
            time.sleep(0.02)
        for i in range(self.npx):
            pushpx(i)
        for i in range(self.npx, 0, -1):
            pushpx(i)
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    def anim_shutdown(self):
        self.pixels.fill((255, 0, 0))
        self.pixels.show()
        time.sleep(0.5)
        self.pixels.fill((0, 0, 0))
        self.pixels.show()
        time.sleep(0.5)
        self.pixels.fill((255, 0, 0))
        self.pixels.show()
        time.sleep(0.5)
        self.pixels.fill((0, 0, 0))
        self.pixels.show()
        time.sleep(0.5)
        self.pixels.fill((255, 0, 0))
        self.pixels.show()
        time.sleep(1)
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

            

class Site(object):
    def __init__(self):
        self.files = {}

        self.update_files()

    def update_files(self):
        dpath = os.path.join(os.getcwd(), 'animations')
        files = [f for f in os.listdir(dpath) if os.path.isfile(os.path.join(dpath, f))]
        self.files = {}
        pattern = re.compile('([a-z]+)-([a-z0-9]+)-([a-zA-Z0-9 ]+)')
        self.files = {}
        for f in files:
            p = pattern.findall(f)[0]
            user = p[0]
            if user not in self.files:
                self.files[user] = []
            md5 = p[1]
            fname = p[2]
            self.files[user].append((md5, fname))
        print(self.files)

    @cherrypy.expose
    def index(self):
        body = """
<!DOCTYPE html>
<html>
    <head>
        <title>Manage your animations</title>
        <style> 
        table {
                border-collapse: collapse;
              }
              
        table, th, td {
                border: 1px solid black;
              }
        </style>
    </head>
    <body>
        <table style="width:50%">
            <tr>
                <th>Name</th>
                <th>MD5</th>
                <th>Delete</th>
            </tr>
"""
        if cherrypy.request.login in self.files:
            for f in self.files[cherrypy.request.login]:
                body += """
            <tr>
                <th>{0}</th>
                <th>{1}</th>
                <th><form action="deleteanim" method="POST">
                    <input type="hidden" name="md5" value="{1}" />
                    <button type="submit">Delete</button>
                </form></th>
            </tr>
""".format(f[1], f[0])


        body += """
        </table>
        <form action="uploadfile" method="POST" enctype="multipart/form-data">
            <p>Add new animation:</p>
            Name: <input type="text" name="name" /><br />
            <input type="file" name="file" /><br />
            <input type="hidden" name="mode" value="animation" />
            <button type="submit">Submit</button>
        </form>
        <form action="uploadfile" method="POST" enctype="multipart/form-data">
            <p>Test animation:</p>
            Name: <input type="hidden" name="name" value="test" /><br />
            <input type="file" name="file" /><br />
            <input type="hidden" name="mode" value="test" />
            <button type="submit">Submit</button>
        </form>
    </body>
</html>
"""

        return body
        # raise cherrypy.HTTPRedirect('/index')

    @cherrypy.expose
    def deleteanim(self, md5):
        name = ''
        for f in self.files[cherrypy.request.login]:
            if f[0] == md5:
                name = '%s-%s-%s' % (cherrypy.request.login, f[0], f[1])
                break
        os.remove(os.path.join(os.getcwd(), 'animations', name))
        self.update_files()
        raise cherrypy.HTTPRedirect('/') # TODO: update redirect target

    def writefile(self, file, out_dir, animname):
        data = b''
        size = 0
        while True:
            d = file.file.read(8192)
            size += len(d)
            data += d
            if size > 50*1024*1024: # 50MB limit
                break # TODO: implement error handling
            if not d:
                break
        filename = '%s-%s' % (cherrypy.request.login, hashlib.md5(data).hexdigest())
        path = os.path.join(os.getcwd(), out_dir, filename)
        if animname != '':
            path += '-' + animname
        with open(path, 'wb') as out:
            out.write(data)
        self.update_files()
        return filename

    @cherrypy.expose
    def uploadfile(self, name, file, mode):
        if cherrypy.request.login is None:
            raise cherrypy.HTTPError(status=403, message='Authenticate first!')
        if len(name) == 0:
            return 'Parameter name cannot be empty'
        for c in name:
            if c not in '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ':
                return 'Only alphanumeric and space characters are accepted in parameter name'
        if mode == 'test':
            global comm
            comm_sem.acquire()
            if comm['test']['testing']:
                return '%s is testing right now...' % comm['test']['username']
            comm_sem.release()
            fn = self.writefile(file, 'temp', '')
            comm_sem.acquire()
            comm['test']['testing'] = True
            comm['test']['username'] = cherrypy.request.login
            comm['test']['filename'] = fn
            comm_sem.release()
        elif mode == 'animation':
            if cherrypy.request.login in self.files and len(self.files[cherrypy.request.login]) >= 3:
                return "Maximum of 3 files can be updated"
            self.writefile(file, 'animations', name[:20])
        else:
            # TODO: error message
            return
        raise cherrypy.HTTPRedirect('/') # TODO: update redirect target

if __name__ == "__main__":
    userpassdict = {'rbasaraba': '1234'}
    config = {
        'global': {
            'server.socket_host': '127.0.0.1',
            'server.socket_port': 8080,
            'server.thread_pool': 8
        },
        '/script.js': {
            'tools.staticfile.on': True,
            'tools.staticfile.filename': os.path.join(os.getcwd(), 'script.js')
        },
        '/log': {
            'tools.staticfile.on': True,
            'tools.staticfile.filename': os.path.join(os.getcwd(), 'server.log')
        },
        '/': {
            'tools.auth_digest.on': True,
            'tools.auth_digest.realm': 'Bradut',
            'tools.auth_digest.get_ha1': auth_digest.get_ha1_dict_plain(userpassdict),
            'tools.auth_digest.key': 'randomsecret',
            'tools.auth_digest.accept_charset': 'UTF-8'
        },
    }
    try:
        ctrl = Controller()
        ctrl.start()
        cherrypy.quickstart(Site(), '/', config)
    except KeyboardInterrupt:
        print('Received Keyboard Interrupt')
        comm_sem.acquire()
        comm['shutdown'] = True
        comm_sem.release()