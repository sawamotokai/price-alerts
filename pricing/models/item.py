import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, List
import uuid
from common.database import Database
from models.model import Model
from dataclasses import dataclass, field


@dataclass(eq=False)
class Item(Model):
    url: str
    tag_name: str
    query: Dict
    price: float = field(default=None)
    _id: str = field(default_factory=lambda :uuid.uuid4().hex)
    collection:str = field(init=False, default='items')

    def load_item(self)->float:
        response = requests.get(self.url)
        content = response.content
        soup = BeautifulSoup(content, 'html.parser')
        element = soup.find(self.tag_name, self.query)
        string_price = element.text.strip()

        pattern = re.compile(r"([1-9]\d{0,2}(,\d\d\d)*(\.\d\d)?|0(\.\d\d)?|[1-9]\d*(\.\d\d)?)")
        match = pattern.search(string_price)
        found_price = match.group(1)

        without_comma = found_price.replace(',', '')
        self.price = float(without_comma)

        return self.price


    def json(self)->Dict:
        return {
            '_id':self._id,
            'url':self.url,
            'tag_name': self.tag_name,
            'query':self.query,
            'price':self.price
        }




