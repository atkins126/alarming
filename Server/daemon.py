#!/usr/bin/env python

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import SocketServer
from urlparse import parse_qs
import os
import cgi
import time
import requests
import subprocess
import config

g_subscribed = []

class S(BaseHTTPRequestHandler):
    def _output(self, code, content):
        self.send_response(code)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
	self.wfile.write(content)

    def do_GET(self):
	try:
		action = parse_qs(self.path[2:]).get("action")[0]
	except:
		action = None

	output = '''<html>

<head>
	<title>Motion camera</title>
</head>

<body onload="onload()">

<script>

function sleep (time) {
	return new Promise((resolve) => setTimeout(resolve, time));
}

function _toggle_alarm(st) {
	document.getElementById("pleasewait").innerHTML = ' <i>Bitte warten</i>...';
	var xhr = new XMLHttpRequest();
	xhr.onreadystatechange = function () {
		var DONE = 4; // readyState 4 means the request is done.
		var OK = 200; // status 200 is a successful return.
		if (xhr.readyState === DONE) {
			if (xhr.status === OK) {
				sleep(5000).then(() => {
					document.location.reload();
				});
			} else {
				alert('Error: ' + xhr.status); // An error occurred during the request.
			}
		}
	};

	var data = new FormData();
	data.append('action', st ? 'motion_on'/*1.3.6.1.4.1.37476.2.4.1.100*/ : 'motion_off'/*1.3.6.1.4.1.37476.2.4.1.101*/);
	xhr.open('POST', '/', true);
	xhr.send(data);
}

function onload() {
	document.getElementById('campic').src = 'http://' + window.location.hostname + ':'''+str(config.motion_stream_port)+'''/';
}

</script>'''

	if ismotionrunning():
		output = output + '<h2>Motion detection ON</h2>';
		output = output + '<p><a href="javascript:_toggle_alarm(0)">Disable motion detection</a><span id="pleasewait"></span></p>';
		output = output + '<p><img id="campic" src="" alt="Camera picture"></p>';
	else:
		output = output + '<h2>Motion detection OFF</h2>';
		output = output + '<p><a href="javascript:_toggle_alarm(1)">Enable motion detection</a><span id="pleasewait"></span></p>';

	output = output + '<h2>Subscribers</h2>'

	found_subs = 0
	for x in g_subscribed[:]:
		if int(time.time()) > x[2]:
			g_subscribed.remove(x)
		else:
			found_subs = found_subs + 1
			output = output + "<p>{0}:{1}</p>".format(x[0], x[1])

	if found_subs == 0:
		output = output + '<p>None</p>'

	output = output + '</body>'
	output = output + '</html>'

	self._output(200, output)

    def do_HEAD(self):
	self._output(200, '')

    def do_POST(self):
	# https://stackoverflow.com/questions/4233218/python-how-do-i-get-key-value-pairs-from-the-basehttprequesthandler-http-post-h
	# TODO: do we need the cgi package, or can we use functions available in this class (e.g. self_parse_qs?)
	ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
	if ctype == 'multipart/form-data':
		postvars = cgi.parse_multipart(self.rfile, pdict)
	elif ctype == 'application/x-www-form-urlencoded':
		length = int(self.headers.getheader('content-length'))
		postvars = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)
	else:
		postvars = {}

	# ---

	global g_subscribed

	if pvget(postvars, "action")[0] == "client_subscribe": # 1.3.6.1.4.1.37476.2.4.1.1
		client_ip      = self.client_address[0]
		client_port    = pvget(postvars, "port")[0]
		client_ttl     = pvget(postvars, "ttl")[0]
		client_targets = pvget(postvars, "targets")

		client_expires = int(time.time()) + int(client_ttl)

		print "Client subscribed: {0}:{1}, searching for targets {2}".format(client_ip, client_port, client_targets)

		# Remove all expired entries, and previous entries of that client
		for x in g_subscribed[:]:
			if int(time.time()) > x[2]:
				g_subscribed.remove(x)
			elif (x[0] == client_ip) and (x[1] == client_port) and (x[3] == client_targets):
				g_subscribed.remove(x)

		# Now add our new client
		g_subscribed.append([client_ip, client_port, client_expires, client_targets])

		# Send parameters of the device(s)
		d = {"action": "client_alert", # 1.3.6.1.4.1.37476.2.4.1.3
		     "targets": ['1.3.6.1.4.1.37476.2.4.2.0', '1.3.6.1.4.1.37476.2.4.2.1002'],
		     "motion_port": config.motion_stream_port,
		     "simulation": "1"}
		requests.post("http://{0}:{1}".format(client_ip, client_port), data=d)

	if pvget(postvars, "action")[0] == "server_alert": # 1.3.6.1.4.1.37476.2.4.1.2
		server_targets = pvget(postvars, "targets")

		found_g = 0

		# TODO: this should be done in parallel threads, so that we can notify every client as fast as possible!
		for x in g_subscribed:
			client_ip      = x[0]
			client_port    = x[1]
			client_expires = x[2]
			client_targets = x[3]
			found_c = 0
			for st in server_targets:
				for ct in client_targets:
					if ct == st:
						found_c = found_c + 1
						found_g = found_g + 1
			if found_c > 0:
				print "ALERT: Will alert client http://{0}:{1} and tell that targets {2} sent an alert".format(client_ip, client_port, server_targets)
				d = {"action": "client_alert", # 1.3.6.1.4.1.37476.2.4.1.3
				     "targets": server_targets,
				     "motion_port": config.motion_stream_port,
				     "simulation": "0"}
				requests.post("http://{0}:{1}".format(client_ip, client_port), data=d)

		if found_g == 0:
			print "ALERT {0}, but nobody is listening!".format(server_targets)


	if pvget(postvars, "action")[0] == "motion_on": # 1.3.6.1.4.1.37476.2.4.1.100
		print "Motion start"
		os.system(os.path.dirname(os.path.abspath(__file__)) + "/motion/motion_start_safe")

	if pvget(postvars, "action")[0] == "motion_off": # 1.3.6.1.4.1.37476.2.4.1.101
		print "Motion stop"
		os.system(os.path.dirname(os.path.abspath(__file__)) + "/motion/motion_stop_safe")

	self._output(200, '')

def pvget(ary, key):
	if ary.get(key) == None:
		return [""]
	else:
		return ary.get(key)

def run(server_class=HTTPServer, handler_class=S, port=8085):
	server_address = ('', port)
	httpd = server_class(server_address, handler_class)
	print 'Starting httpd...'
	httpd.serve_forever()

def ismotionrunning():
	p = subprocess.Popen(["ps", "aux"], stdout=subprocess.PIPE)
	out, err = p.communicate()
	try:
		return ('/usr/bin/motion' in str(out))
	except:
		res = os.system("pidof -x /usr/bin/motion > /dev/null")
		return (res >> 8) == 0

if __name__ == "__main__":
	from sys import argv

	if len(argv) == 2:
		run(port=int(argv[1]))
	else:
		run()
