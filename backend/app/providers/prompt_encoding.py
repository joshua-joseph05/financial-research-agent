"""Shared JSON prompt encoding, with a lossless candidate for cost experiments."""
import json


def compact_prompt(payload):
    # Preserve every key and value, including whitespace inside source excerpts.
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def encode_prompt(payload):
    # Keep established formatting until matched cost/quality tests justify a switch.
    return json.dumps(payload)
