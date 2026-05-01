from fastapi import FastAPI
from pydantic import BaseModel
app=FastAPI() #backend system 

class Item(BaseModel):
    item_name: str
    price: int

@app.post("/menu")
def home(Item):
    return{
     

    }