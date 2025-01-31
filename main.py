#!/usr/bin/env python3

import json
import logging
import re
import requests
from multiprocessing.pool import ThreadPool
import os

import openai
import srt

import altair as alt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from datetime import datetime, timedelta

from langchain.embeddings import OpenAIEmbeddings
from langchain.llms import OpenAI
from langchain.schema import Document
from requests.exceptions import HTTPError
from sklearn.cluster import KMeans

from functions import load_inventory, load_srt, select_docs, get_summary
from functions import THREAD_COUNT, OUTPUT_FOLDER_NAME

TITLE = "News Summary"
DESC = """
This experimental service presents summaries of the top news stories of archived TV News Channels from around the world.  Audio from those archives are transcribed and translated using Google Cloud services and then stories are identified and summarized using various AI LLMs (we are currently experimenting with several, including Vicuna and GPT-3.5).

This is a work-in-progress and you should expect to see poorly transcribed, translated and/or summarized text and some "hallucinations".

Questions and feedback are requested and appreciated!  How might this service be more useful to you?  Please share your thoughts with info@archive.org.
"""
ICON = "https://archive.org/favicon.ico"
VICUNA = "http://fc6000.sf.archive.org:8000/v1"

IDDTRE = re.compile(r"^.+_(\d{8}_\d{6})")

BGNDT = pd.to_datetime("2022-03-25").date()
ENDDT = (datetime.now() - timedelta(hours=30)).date()

CHANNELS = {
  "": "-- Select --",
  "ESPRESO": "Espreso TV",
  "RUSSIA1": "Russia-1",
  "RUSSIA24": "Russia-24",
  "1TV": "Channel One Russia",
  "NTV": "NTV",
  "BELARUSTV": "Belarus TV",
  "IRINN": "Islamic Republic of Iran News Network"
}

st.set_page_config(page_title=TITLE, page_icon=ICON, layout="centered", initial_sidebar_state="collapsed")
st.title(TITLE)
st.info(DESC)

load_srt = (st.cache_resource(show_spinner=False))(load_srt)
load_inventory = (st.cache_resource(show_spinner=False))(load_inventory)
select_docs = (st.cache_resource(show_spinner="Loading and processing transcripts (`may take up to 2 minutes`)..."))(select_docs)


def id_to_time(id, start=0):
  dt = IDDTRE.match(id).groups()[0]
  return datetime.strptime(dt, "%Y%m%d_%H%M%S") + timedelta(seconds=start)


def draw_summaries(json_output):
  for smr in json_output:
    try:
      st.subheader(smr.get("title", "[EMPTY]"))
      cols = st.columns([1, 2])
      with cols[0]:
        components.iframe(f'https://archive.org/embed/{smr["id"]}?start={smr["start"]}&end={smr["end"]}')
      with cols[1]:
        st.write(smr.get("description", "[EMPTY]"))
      with st.expander(f'[{id_to_time(smr["id"], smr["start"])}] `{smr.get("category", "[EMPTY]").upper()}`'):
        st.caption(smr["transcript"])
    except json.JSONDecodeError as _:
      pass


@st.cache_resource(show_spinner="Summarizing...")
def gather_summaries(dt, ch, lg, lm, ck, ct, _seldocs):
  summary_args = [(d,lm) for d in _seldocs]
  with ThreadPool(THREAD_COUNT) as pool:
    summaries = pool.starmap(get_summary, summary_args)
  return summaries

qp = st.experimental_get_query_params()
if "date" not in st.session_state and qp.get("date"):
    st.session_state["date"] = datetime.strptime(qp.get("date")[0], "%Y-%m-%d").date()
if "chan" not in st.session_state and qp.get("chan"):
    st.session_state["chan"] = qp.get("chan")[0]
if "lang" not in st.session_state and qp.get("lang"):
    st.session_state["lang"] = qp.get("lang")[0]
if "llm" not in st.session_state and qp.get("llm"):
    st.session_state["llm"] = qp.get("llm")[0]
if "chunk" not in st.session_state and qp.get("chunk"):
    st.session_state["chunk"] = int(qp.get("chunk")[0])
if "count" not in st.session_state and qp.get("count"):
    st.session_state["count"] = int(qp.get("count")[0])

with st.expander("Configurations"):
  lm = st.radio("LLM", ["OpenAI", "Vicuna"], key="llm", horizontal=True)
  ck = st.slider("Chunk size (sec)", value=30, min_value=3, max_value=120, step=3, key="chunk")
  ct = st.slider("Cluster count", value=20, min_value=1, max_value=50, key="count")

cols = st.columns([1, 2, 1])
dt = cols[0].date_input("Date", value=ENDDT, min_value=BGNDT, max_value=ENDDT, key="date").strftime("%Y%m%d")
ch = cols[1].selectbox("Channel", CHANNELS, format_func=lambda x: CHANNELS.get(x, ""), key="chan")
lg = cols[2].selectbox("Language", ["English", "Original"], key="lang")

if not ch:
  st.info(f"Select a channel to summarize for the selected day.")
  st.stop()

st.experimental_set_query_params(**st.session_state)

if lm == "Vicuna":
  openai.api_key = "EMPTY"
  openai.api_base = VICUNA

try:
  inventory = load_inventory(ch, dt, lg)
except HTTPError as _:
  st.warning(f"Inventory for `{CHANNELS.get(ch, 'selected')}` channel is not available for `{dt[:4]}-{dt[4:6]}-{dt[6:8]}` yet, try selecting another date!", icon="⚠️")
  st.stop()

with st.expander("Program Inventory"):
  inventory

if f"{dt}-{ch}-{lm}-{lg}.json" in os.listdir(f"./{OUTPUT_FOLDER_NAME}"):
    print("FOUND FILE")
    summaries = open(f"./{OUTPUT_FOLDER_NAME}/{dt}-{ch}-{lm}-{lg}.json", "r")
    summaries_json = json.loads(summaries.read())
    draw_summaries(summaries_json)
else:
  seldocs = select_docs(dt, ch, lg, lm, ck, ct, inventory)
  summaries_json = gather_summaries(dt, ch, lg, lm, ck, ct, seldocs)
  with open(f"{OUTPUT_FOLDER_NAME}/{dt}-{ch}-{lm}-{lg}.json", 'w+') as f:
    f.write(json.dumps(summaries_json, indent=2))
  draw_summaries(summaries_json)
