#    __  ___     __   _ __           ___   ___  ____
#   /  |/  /__  / /  (_) /_____ ____/ _ | / _ \/  _/
#  / /|_/ / _ \/ _ \/ /  '_/ -_)___/ __ |/ ___// /
# /_/  /_/\___/_.__/_/_/\_\\__/   /_/ |_/_/  /___/

#-------------#
#   IMPORTS   #
#-------------#

# FastAPI Imports
from typing import Annotated
from fastapi import Body,FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Other Imports
import os
from dotenv import load_dotenv
import requests
import json
from datetime import datetime
from google.protobuf.timestamp_pb2 import Timestamp

#------------------------#
#   INITIALIZE FASTAPI   #
#------------------------#

app = FastAPI()                                     # Creates FastAPI App
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)                                                   # Allows cross-origin requests


#----------------------------#
#   INITIALIZE GLOBAL VARS   #
#----------------------------#

load_dotenv()
ROUTING_API_URL = os.getenv('ROUTING_API_URL')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
FIELD_MASKS = {
    # Determines what data we get back from Google Maps

    # routes.* masks cover the total journey (when returning a multimodal route we will sum these)
    'routes.distanceMeters',
    'routes.duration',
    'routes.staticDuration',

    # routes.legs.* masks cover each 'leg' of the journey (generally 1 per route for this use case, additional modes will be merged in as new legs of the journey)
    'routes.legs.startLocation',
    'routes.legs.endLocation',
    'routes.legs.distanceMeters',
    'routes.legs.duration',
    'routes.legs.staticDuration',
    'routes.legs.polyline', # Intentionally only including polyline starting at leg level to handle data merge in multimodal scenario

    # routes.legs.steps.* masks cover each step of each 'leg', such as cycling on an individual 
    'routes.legs.steps.startLocation',
    'routes.legs.steps.endLocation',
    'routes.legs.steps.distanceMeters',
    'routes.legs.steps.staticDuration',
    'routes.legs.steps.polyline',
    'routes.legs.steps.transitDetails',
    'routes.legs.steps.travelMode'
}
HEADERS = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': ','.join(FIELD_MASKS)
        }
REQUEST_PREFS_GLOBAL = {
        'computeAlternativeRoutes': False,
        'languageCode': 'en',
        'units': 'IMPERIAL'
    }


#-----------------------#
#   DEFINE DATA MODEL   #
#-----------------------#

class RouteRequest(BaseModel):
    origin_place_id: str
    dest_place_id: str


#---------------------------#
#   SANITY CHECK ENDPOINT   #
#---------------------------#

@app.get("/")                                       # Sanity check endpoint to ensure server is accessible
async def sanity_check():
    return {
        "message": "Welcome to the Mobike API!"
    }


#----------------------#
#   ROUTING ENDPOINT   #
#----------------------#

@app.post("/routing")
async def routing(route_request: RouteRequest):
    result = unimodal_transit(route_request)
    return result


#------------------------------#
#   ROUTING HELPER FUNCTIONS   #
#------------------------------#

def unimodal_cycling(route_request: RouteRequest, departure_time: datetime = datetime.now()) -> str:
    body = {
        'origin': {
            'placeId': route_request.origin_place_id
        },
        'destination': {
            'placeId': route_request.dest_place_id
        },
        'travelMode': 'BICYCLE',
        'departureTime': retrieve_pb_timestamp(departure_time).ToJsonString()

    }
    response = requests.post(ROUTING_API_URL, data=json.dumps(body | REQUEST_PREFS_GLOBAL), headers=HEADERS)
    return response.json()

def unimodal_transit(route_request: RouteRequest, departure_time: datetime = datetime.now()) -> str:
    body = {
        'origin': {
            'placeId': route_request.origin_place_id
        },
        'destination': {
            'placeId': route_request.dest_place_id
        },
        'travelMode': 'TRANSIT',
        'departureTime': retrieve_pb_timestamp(departure_time).ToJsonString()
    }
    response = requests.post(ROUTING_API_URL, data=json.dumps(body | REQUEST_PREFS_GLOBAL), headers=HEADERS)
    return response.json()

def bimodal(route_request: RouteRequest, departure_time: datetime = datetime.now()) -> str:
    transit_route = unimodal_transit(route_request, departure_time)


#------------------------------#
#   GENERAL HELPER FUNCTIONS   #
#------------------------------#

def retrieve_pb_timestamp(time_datetime: datetime) -> Timestamp:
    time_timestamp = Timestamp()
    time_timestamp.FromDatetime(time_datetime)
    return time_timestamp