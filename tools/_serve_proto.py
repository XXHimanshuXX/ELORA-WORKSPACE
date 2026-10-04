import http.server
import os
import socketserver

os.chdir(r"D:\Coding\ELORA Workspace\.ohmyagent\design\v1")
Handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("127.0.0.1", 8766), Handler) as httpd:
    httpd.serve_forever()
