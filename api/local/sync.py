from http.server import BaseHTTPRequestHandler

from lib import web


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            web.sync_post(self)
        except Exception as error:
            web.fail(self, error)
