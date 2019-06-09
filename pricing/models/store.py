import re

from common.database import Database
from models.model import Model
from typing import Dict
import uuid
from dataclasses import dataclass, field

@dataclass(eq=False)
class Store(Model):
    name: str
    url_prefix: str
    tag_name: str
    query: Dict
    _id: str = field(default_factory=lambda: uuid.uuid4().hex)
    collection:str = field(init=False, default='stores')


    def json(self):
        return {
            "_id":self._id,
            "name":self.name,
            "url_prefix":self.url_prefix,
            'query':self.query,
            'tag_name':self.tag_name
        }


    @classmethod
    def get_by_name(cls, store_name:str)->"Store":
        return cls.find_one_by('name', store_name)


    @classmethod
    def get_by_url_prefix(cls, url_prefix)->"Store":
        url_regex = {"$regex" : "^{}".format(url_prefix)}
        return cls.find_one_by("url_prefix", url_regex)


    @classmethod
    def get_by_url(cls, url:str)->"Store":
        """
        Return a store from an item url
        :param url:
        :return: a Store
        """
        pattern = re.compile(r"(https?:\/\/.*?\/)")
        match = pattern.search(url)
        url_prefix = match.group(1)
        return cls.get_by_url_prefix(url_prefix)