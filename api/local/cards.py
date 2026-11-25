from http.server import BaseHTTPRequestHandler

from lib import web


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            web.cards_get(self)
        except Exception as error:
            web.fail(self, error)

    def do_POST(self):
        try:
            web.cards_post(self)
        except Exception as error:
            web.fail(self, error)

    def do_PATCH(self):
        try:
            web.card_patch(self)
        except Exception as error:
            web.fail(self, error)

    def do_DELETE(self):
        try:
            web.card_delete(self)
        except Exception as error:
            web.fail(self, error)
