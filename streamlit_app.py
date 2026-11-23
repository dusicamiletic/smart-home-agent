"""Streamlit chat front-end -- the "or Streamlit" half of the brief's
minimal-interface requirement (adk web is the other half, still available
via `adk web` / the `smart-home-agent` docker-compose service).

Talks to `root_agent` in-process through ADK's own Runner, not over HTTP:
the agent package already owns the catalogue, tools and guardrails, so this
file is presentation only, same as `agent.py`'s tool wrappers are the only
bridge between the pure-Python tool layer and ADK.
"""

from __future__ import annotations

import asyncio
import uuid

import streamlit as st
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from smart_home_agent.agent import root_agent
from streamlit_helpers import find_products, format_price, hub_badge, needs_hardware, products_in_reply

APP_NAME = "smart_home_agent"
USER_ID = "streamlit-user"
THUMBNAIL_WIDTH = 110

st.set_page_config(page_title="Smart Home Assistant", page_icon="\U0001f3e0")


@st.cache_resource
def _get_runner() -> tuple[Runner, InMemorySessionService]:
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)
    return runner, session_service


runner, session_service = _get_runner()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.history = []
    asyncio.run(
        session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=st.session_state.session_id)
    )

st.title("\U0001f3e0 Smart Home Assistant")
st.caption(
    "Bilingual (DE/EN) shopping assistant for connected smart home products -- "
    "recommendations, comparisons, and ecosystem compatibility checks."
)

with st.sidebar:
    if st.button("New conversation"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.subheader("What I've noted about you")
    session = asyncio.run(session_service.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=st.session_state.session_id))
    noted = {key.removeprefix("user:"): value for key, value in (session.state if session else {}).items() if key.startswith("user:")}
    if noted:
        for key, value in noted.items():
            st.write(f"**{key}**: {value}")
    else:
        st.caption("Nothing yet -- mention your ecosystem, budget, or rooms and I'll remember it for this conversation.")


def _render_product_rows(products: list[dict]) -> None:
    """Layout A: compact stacked rows, thumbnail and text sharing one row so
    there is no separate "which image is which" step. A hub warning is a
    positive fact only -- `needs_hardware` renders nothing for False,
    unknown, or hub-type hardware itself, so the list never states "not
    stated" and a hub never warns about needing itself."""
    for product in products:
        thumb_col, text_col = st.columns([1, 5])
        with thumb_col:
            st.image(product["image_url"], width=THUMBNAIL_WIDTH)
        with text_col:
            st.markdown(f"**[{product['title']}]({product['url']})**  {format_price(product.get('price'))}")
            badge = hub_badge(product)
            if badge:
                st.markdown(badge)

        required = product.get("required_products") or []
        if needs_hardware(product) and required and required[0].get("url") and required[0].get("image_url"):
            hardware = required[0]
            _, hw_thumb_col, hw_text_col = st.columns([0.4, 1, 5])
            with hw_thumb_col:
                st.image(hardware["image_url"], width=THUMBNAIL_WIDTH - 20)
            with hw_text_col:
                st.markdown(f"↳ **[{hardware['name']}]({hardware['url']})**  {format_price(hardware.get('price'))}")

        st.markdown("")


for message in st.session_state.history:
    with st.chat_message(message["role"]):
        st.markdown(message["text"])
        _render_product_rows(message.get("products", []))

prompt = st.chat_input("Ask about smart home products... / Fragen Sie mich etwas...")
if prompt:
    st.session_state.history.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    async def _run_turn() -> tuple[str, dict[str, dict]]:
        reply_parts = []
        catalog: dict[str, dict] = {}
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for event in runner.run_async(user_id=USER_ID, session_id=st.session_state.session_id, new_message=message):
            if not (event.content and event.content.parts):
                continue
            for part in event.content.parts:
                if part.text:
                    reply_parts.append(part.text)
                if part.function_response and part.function_response.response:
                    catalog.update(find_products(part.function_response.response))
        return "".join(reply_parts), catalog

    with st.chat_message("assistant"):
        with st.spinner("..."):
            reply, catalog = asyncio.run(_run_turn())
        products = products_in_reply(reply, catalog)
        st.markdown(reply)
        _render_product_rows(products)
    st.session_state.history.append({"role": "assistant", "text": reply, "products": products})
