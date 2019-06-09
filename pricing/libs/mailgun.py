from requests import post, Response
from typing import List
import os


class MailgunException(Exception):
    def __init__(self, message:str):
        self.message = message


class Mailgun:


    FROM_TITLE = 'Pricing Service'
    FROM_EMAIL = 'do-not-reply@sandbox3d6a7654eefd4548bb5467d23dffdbf3.mailgun.org'

    @classmethod
    def send_mail(cls, email: List[str], subject: str, text: str, html: str):
        MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY', None)
        MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN")
        if MAILGUN_API_KEY is None:
            raise MailgunException('Failed to load Mailgun API Key.')
        if MAILGUN_DOMAIN is None:
            raise MailgunException('Failed to load Mailgun domain.')

        response = post(
            f"{MAILGUN_DOMAIN}/messages",
            auth=("api", f"{MAILGUN_API_KEY}"),
            data={"from": f"{cls.FROM_TITLE} <{cls.FROM_EMAIL}>",
                  "to": [email],
                  "subject": subject,
                  "text": text,
                  "html":html})

        if response.status_code != 200:
            print(response.json())
            raise MailgunException('An error occured while sending an email.')
        return response


