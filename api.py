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
from datetime import timedelta
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

    # routes.legs.steps.* masks cover each step of each 'leg', such as cycling on an individual street or taking a specific bus
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

class Coordinate(BaseModel):
    latitude: float
    longitude: float

class RouteRequest(BaseModel):
    origin: Coordinate
    destination: Coordinate


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
    result = bimodal(route_request)
    return result


#------------------------------#
#   ROUTING HELPER FUNCTIONS   #
#------------------------------#

def unimodal_cycling(route_request: RouteRequest, departure_time: datetime = datetime.utcnow()) -> str:
    body = {
        'origin': {
            'location': {
                'latLng': {
                    'latitude': route_request.origin.latitude,
                    'longitude': route_request.origin.longitude
                }
            }
        },
        'destination': {
            'location': {
                'latLng': {
                    'latitude': route_request.destination.latitude,
                    'longitude': route_request.destination.longitude
                }
            }
        },
        'travelMode': 'BICYCLE',
        'departureTime': retrieve_pb_timestamp(departure_time).ToJsonString()
    }
    response = requests.post(ROUTING_API_URL, data=json.dumps(body | REQUEST_PREFS_GLOBAL), headers=HEADERS)
    print(retrieve_pb_timestamp(datetime.utcnow()))
    print(retrieve_pb_timestamp(departure_time))
    return response.json()

def unimodal_transit(route_request: RouteRequest, departure_time: datetime = datetime.utcnow()) -> str:
    body = {
        'origin': {
            'location': {
                'latLng': {
                    'latitude': route_request.origin.latitude,
                    'longitude': route_request.origin.longitude
                }
            }
        },
        'destination': {
            'location': {
                'latLng': {
                    'latitude': route_request.destination.latitude,
                    'longitude': route_request.destination.longitude
                }
            }
        },
        'travelMode': 'TRANSIT',
        'departureTime': retrieve_pb_timestamp(departure_time).ToJsonString()
    }
    response = requests.post(ROUTING_API_URL, data=json.dumps(body | REQUEST_PREFS_GLOBAL), headers=HEADERS)
    return response.json()

def bimodal(route_request: RouteRequest, departure_time: datetime = datetime.utcnow()) -> str:
    transit_first_run = unimodal_transit(route_request, departure_time)
    legs = transit_first_run['routes'][0]['legs']
    for leg in legs:
        steps_without_walk = [step for step in leg['steps'] if step['travelMode'] != 'WALK']
        leg['steps'] = steps_without_walk
    transit_start_latlng = legs[0]['steps'][0]['transitDetails']['stopDetails']['departureStop']['location']['latLng']
    transit_end_latlng = legs[len(legs)-1]['steps'][len(legs[len(legs)-1]['steps'])-1]['transitDetails']['stopDetails']['departureStop']['location']['latLng']
    transit_route_request = RouteRequest(
        origin = Coordinate(
            latitude = transit_start_latlng['latitude'], 
            longitude = transit_start_latlng['longitude']
            ),
        destination = Coordinate(
            latitude = transit_end_latlng['latitude'], 
            longitude = transit_end_latlng['longitude']
            )
        )
    departure_time = datetime.utcnow() + timedelta(seconds=5)
    cycling_first_mile = unimodal_cycling(
        RouteRequest(
            origin = route_request.origin,
            destination = transit_route_request.origin
        ),
        departure_time = departure_time
        )
    cycling_first_mile_elapsed = timedelta(seconds=float(cycling_first_mile['routes'][0]['duration'].rstrip('s')))
    transit_second_run = unimodal_transit(
        transit_route_request,
        departure_time=departure_time+cycling_first_mile_elapsed
        )
    transit_second_run_elapsed = timedelta(seconds=float(transit_second_run['routes'][0]['duration'].rstrip('s')))
    cycling_last_mile = unimodal_cycling(
        RouteRequest(
            origin = transit_route_request.destination,
            destination = route_request.destination
            ),
        departure_time=departure_time+cycling_first_mile_elapsed+transit_second_run_elapsed)
    final_routing = dict(cycling_first_mile)
    final_routing['routes'][0]['distanceMeters'] += (transit_second_run['routes'][0]['distanceMeters'] + cycling_last_mile['routes'][0]['distanceMeters'])
    final_routing['routes'][0]['duration'] = f"{float(final_routing['routes'][0]['duration'].rstrip('s')) + float(transit_second_run['routes'][0]['duration'].rstrip('s')) + float(cycling_last_mile['routes'][0]['duration'].rstrip('s'))}s"
    final_routing['routes'][0]['staticDuration'] = f"{float(final_routing['routes'][0]['staticDuration'].rstrip('s')) + float(transit_second_run['routes'][0]['staticDuration'].rstrip('s')) + float(cycling_last_mile['routes'][0]['staticDuration'].rstrip('s'))}s"
    final_routing['routes'][0]['legs'].append(transit_second_run['routes'][0]['legs'])
    final_routing['routes'][0]['legs'].append(cycling_last_mile['routes'][0]['legs'])
    return final_routing

#------------------------------#
#   GENERAL HELPER FUNCTIONS   #
#------------------------------#

def retrieve_pb_timestamp(time_datetime: datetime) -> Timestamp:
    time_timestamp = Timestamp()
    time_timestamp.FromDatetime(time_datetime)
    return time_timestamp