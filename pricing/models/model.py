from abc import ABCMeta, abstractclassmethod
from common.database import Database
from typing import TypeVar, List, Type, Dict, Union

T=TypeVar('T', bound='Model')

class Model:
    collection: str
    _id: str
    def __init__(self, *args, **kwargs):
        pass

    @abstractclassmethod
    def json(cls)->Dict:
        raise NotImplementedError



    def save_to_mongo(self):
        Database.update(self.collection, {"_id":self._id}, self.json())


    def remove_from_mongo(self):
        Database.remove(self.collection, {"_id":self._id})


    @classmethod
    def all(cls:Type[T])->List[T]:
        elems_from_mongo = Database.find(cls.collection, {})
        return [cls(**elem) for elem in elems_from_mongo]

    @classmethod
    def find_one_by(cls:Type[T], attribute:str, value:Union[str, Dict])->T:
        return cls(**Database.find_one(cls.collection, {attribute: value}))

    @classmethod
    def find_many_by(cls:Type[T], attribute:str, value:Union[Dict,str])->List[T]:
        return [cls(**elem) for elem in Database.find(cls.collection, {attribute: value})]

    @classmethod
    def get_by_id(cls:Type[T], _id:str)->T:
        return cls.find_one_by('_id', _id)

