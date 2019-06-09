from typing import Dict, List
from models.item import Item
import uuid
from common.database import Database
from models.model import Model
from dataclasses import dataclass, field
from models.user.user import User
from libs.mailgun import Mailgun



@dataclass(eq=False)
class Alert(Model):
    name: str
    item_id:str
    price_limit: float
    user_email:str
    _id:str = field(default_factory= lambda:uuid.uuid4().hex)
    collection:str = field(init=False, default='alerts')
    def __post_init__(self):
        self.item = Item.get_by_id(self.item_id)
        self.user = User.find_by_email(self.user_email)


    def json(self)->Dict:
        return {
            "name":self.name,
            "item_id":self.item_id,
            "price_limit":self.price_limit,
            "_id":self._id,
            'user_email':self.user_email
        }


    def load_item_price(self)->float:
        self.item.load_item()
        self.item.save_to_mongo()
        return self.item.price


    def notify_if_price_reached(self):
        if self.item.price < self.price_limit:
            Mailgun.send_mail(
                [self.user_email],
                f"Notification for {self.name}",
                f"""Your alert {self.name} has reached a price under {self.price_limit}. The latest price is 
{self.item.price}. Go to this address to check your item{self.item.url}.""",
                f"""<p>Your alert {self.name} has reached a price under {self.price_limit}.</p><p>The latest price is 
{self.item.price}. Click <a href='{self.item.url}'>here</a> to check your item.</p>"""
            )
