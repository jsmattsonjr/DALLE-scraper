#!/usr/bin/env python3

# This script requires exiftool (https://exiftool.org/) to write the prompt
# into the .PNG file as its description. The description of a .PNG file can
# be viewed from Preview using CMD-i (or Tools -> Show Inspector).

from requests.exceptions import RequestException
from datetime import datetime
from itertools import count
from io import BytesIO
from PIL import Image
import subprocess
import requests
import json
import uuid
import time
import os

# Path to store the images
directory = os.path.expanduser('~/Desktop/DALLE')
timestamp = f'{directory}/.timestamp'

# Authorization key, extracted from a web browser session to
# https://labs.openai.com/history (debug network traffic)
# or using this Chrome extension:
# https://chrome.google.com/webstore/detail/cdedbiepgdnfimgogajjngbjcghhdfcl
authkey = 'sess-........................................'

# Build a dictionary of all generations created since startTime, indexed
# by creation time.
def scan(startTime):
    index = {}
    # Loop through all task pages starting at 1. (There is no page 0.)
    for i in count(start=1):
        print(f'Requesting history page {i}')
        url = f'https://labs.openai.com/api/labs/tasks?page={i}&limit=8'
        response = requests.get(url,
                                headers={'Content-Type':'application/json',
                                         'Authorization':'Bearer ' + authkey})
        response.raise_for_status()

        # If the page is empty, we must be done.
        if not response.json()['data']:
            return index

        for datum in response.json()['data']:
            # Images created before the timestamp have already been processed.
            # Note that images are listed from most recent to oldest, so
            # timestamps are decreasing. If we reach the startTime, we're
            # done. Note that this assumes the previous scrape processed
            # all images created at startTime.
            created = int(datum['created'])
            if created <= startTime:
                return index

            if created in index:
                index[created] = index[created] + [datum]
            else:
                index[created] = [datum]

# Try to download a single image file. In case of a download failure, retry
# a few times with exponential backoff.
def download(url):
    backoff = 2
    while True:
        try:
            return Image.open(BytesIO(requests.get(url).content))
        except Exception as e:
            if backoff >= 30:
                raise e
            print(f'Error "{e}" downloading image. Retry in {backoff} seconds')
            time.sleep(backoff)
            backoff = backoff * 2

# Fetch all (four, usually) of the images from a single set.
def fetch(datum):
    fileset = []

    # Begin each filename with the image creation date/time, in human
    # readable form.
    created = int(datum['created'])
    prefix = datetime.fromtimestamp(created).strftime("%Y-%m-%d-%H-%M") + '-'

    for generation in datum['generations']['data']:
        url = generation['generation']['image_path']
        print(f'Requesting image {url}')
        try:
            with download(url) as image:
                # Save the downloaded image as a .PNG file
                basename = prefix + str(uuid.uuid4())
                filename = f'{directory}/{basename}.png'
                print(f'Saving as {filename}')
                image.save(filename, optimize=True)
                fileset = fileset + [filename]
        except Exception as e:
            print(f'Scraping aborted with error "{e}"')
            if fileset:
                print(f'Removing {fileset}')
                for file in fileset:
                    os.remove(file)
            raise e

    # For some generations (Edits? Variations?) there is no "caption."
    # Just leave the description blank.
    if 'caption' in datum['prompt']['prompt']:
        prompt = datum['prompt']['prompt']['caption']
        print(f'Captioning {len(fileset)} images with "{prompt}"')
        subprocess.run(['exiftool', '-overwrite_original',
                        '-XMP-dc:Description=' + prompt] + fileset)

    # Set the file accessed/modified times to the image creation time.
    for file in fileset:
        os.utime(file, (created, created))

    return created

# Create the destination directory, if it doesn't exist.
try:
    os.mkdir(directory)
except OSError:
    pass

# Read the timestamp (of last image processed) from the .timestamp file,
# if it exists.
latest = 0
if os.path.exists(timestamp):
    with open(timestamp, 'r') as f:
        latest = int(next(f))

# Get the list of images to download. This is a stateless query, so
# no cleanup is necessary in the event of an error.
try:
    index = scan(latest)
except Exception as e:
    print(f'Indexing aborted with error "{e}"')
    exit(255)

# Download the images, from oldest to newest. When all images from a
# specific time (second granularity) are downloaded, record the timestamp,
# so that we know where to start the next time the script is run.
try:
    for key in sorted(index.keys()):
        for datum in index[key]:
            latest = fetch(datum)
        # Update the .timestamp file.
        with open(timestamp, 'w') as f:
            print(latest, file=f)
except:
    exit(255)
else:
    print('Scraping complete')

exit(0)
