"""Canonical field `description_long` (t_d2f75685). acompio rejected listing 47872152 with "Insufficient description". The text is written by the batch from
seniorcaresolutions.co (original wording, never invented in code); this module only VALIDATES it before any form is touched.

Rules: 100 to 300 characters; full sentences (starts with a capital, ends with . ! or ?); no phone number, no email, no URL, no street address / ZIP / PO box /
city-state-ZIP line, no hours or days of the week. validate(text) -> the stripped text, or raises DescriptionError naming the rule.
The identity file may carry BIZ.SCC.description_long; build_runner.nap_from_identity exposes it as the NAP key {description_long} only when it passes.
"""
import re

MIN_LEN, MAX_LEN = 100, 300


class DescriptionError(Exception):
    pass


_PHONE = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b|\b\d{3}[\s.\-]\d{4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"(?i)\bhttps?://|\bwww\.|\b[a-z0-9-]+\.(?:com|net|org|co|us|io|info|biz)\b")
_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_STREET = re.compile(r"(?i)\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Za-z0-9.'-]+\s+){0,3}(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd|court|ct|way|highway|hwy|parkway|pkwy|circle|cir|place|pl|suite|ste)\b\.?")
_POBOX = re.compile(r"(?i)\bp\.?\s?o\.?\s?box\b")
_CITYSTATE = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s?(?:[A-Z]{2})\b")
_HOURS = re.compile(r"(?i)\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b|\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)\b|\b24\s?/\s?7\b|\bopen\s+(?:daily|weekdays|weekends)\b|\bbusiness hours\b|\bhours of operation\b|\b(?:from|between)\s+\d{1,2}\s+(?:to|and|-)\s+\d{1,2}\b")


def validate(text):
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t: raise DescriptionError("description_long is empty")
    if len(t) < MIN_LEN: raise DescriptionError("description_long is too short (%d characters, need at least %d)" % (len(t), MIN_LEN))
    if len(t) > MAX_LEN: raise DescriptionError("description_long is too long (%d characters, at most %d)" % (len(t), MAX_LEN))
    if _EMAIL.search(t): raise DescriptionError("description_long has an email address")
    if _URL.search(t): raise DescriptionError("description_long has a web address")
    if _PHONE.search(t): raise DescriptionError("description_long has a phone number")
    if _STREET.search(t) or _POBOX.search(t) or _ZIP.search(t) or _CITYSTATE.search(t): raise DescriptionError("description_long has address data (street, PO box, ZIP or City, ST)")
    if _HOURS.search(t): raise DescriptionError("description_long has business hours or days of the week")
    if not re.match(r"[A-Z0-9]", t) or t[-1] not in ".!?": raise DescriptionError("description_long must be full sentences (start with a capital, end with a period)")
    if len(re.findall(r"[.!?](?:\s|$)", t)) < 2: raise DescriptionError("description_long needs at least two sentences")
    return t
