from http.server import BaseHTTPRequestHandler

from lib import web


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            web.rows_get(self)
        except Exception as error:
            web.fail(self, error)
