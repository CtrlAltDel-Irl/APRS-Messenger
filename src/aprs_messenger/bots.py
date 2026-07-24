"""Popular APRS bots / gateways and usage examples."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AprsBot:
    callsign: str  # APRS-IS destination address
    name: str
    description: str
    example: str
    tips: str = ""
    list_label: str = ""  # optional UI label (e.g. SMS instead of SMSGTE)

    @property
    def display_call(self) -> str:
        return self.list_label or self.callsign


# Well-known APRS-IS messaging bots / gateways.
# Examples follow common public documentation; services change — verify before use.
POPULAR_BOTS: list[AprsBot] = [
    AprsBot(
        callsign="SMS",
        name="SMS",
        list_label="SMS",
        description="Send and receive SMS text messages via APRS. Opt in @ https://aprs.wiki/",
        example="@15551234567 Hello from APRS",
        tips="Opt in @ https://aprs.wiki/",
    ),
    AprsBot(
        callsign="EMAIL-2",
        name="Email Gateway",
        description="Send short email messages over APRS-IS.",
        example="user@example.com Hello from the radio",
        tips="Format: email@domain.com then a space then your short message (keep under ~67 chars total).",
    ),
    AprsBot(
        callsign="APTDAP",
        name="APRS to Dapnet Bot",
        description="Send messages to Dapnet Pagers.",
        example="M0RWV Hi Scot.",
        tips="<Callsign> <Message>",
    ),
    AprsBot(
        callsign="WTSAPP",
        name="Whatsapp Bot",
        description="Send and receive whatsapp messages.",
        example="@+447707712345 Hi this is my message",
        tips="Follow up messages don't require phone number, just type your message.",
    ),
    AprsBot(
        callsign="WXBOT",
        name="Weather Bot",
        description="Request weather forecasts / conditions by message.",
        example="TODAY,TONIGHT,TOMORROW,12345,LAX",
        tips="Try 'help' first. Many requests use a city, ZIP, or grid (e.g. 'metro Boston' or your grid).",
    ),
    AprsBot(
        callsign="MPAD",
        name="Multi-Purpose APRS Daemon",
        description="Information and utility commands (help, time, wx, etc.).",
        example="help",
        tips="Send 'help' for the command list. Common: time, wx, where CALL, etc.",
    ),
    AprsBot(
        callsign="WHO-IS",
        name="Callsign Lookup",
        description="Look up amateur callsign information.",
        example="MI7DJT",
        tips="Message body is usually just the callsign you want to look up.",
    ),
    AprsBot(
        callsign="ANSRVR",
        name="APRS Thursday Server",
        description="Group CQ / bulletin-style messaging on APRS.",
        example="CQ HOTG Happy APRS Thursday from ",
        tips="To Unsubsribe from receiving group messages type: U HOTG",
    ),
    AprsBot(
        callsign="CQSRVR",
        name="CQ Server",
        description="Group CQ / bulletin-style messaging on APRS.",
        example="CQ TEST de MYCALL listening",
        tips="See CQSRVR docs for group names and etiquette. Keep messages short.",
    ),
    AprsBot(
        callsign="WLNK-1",
        name="Winlink Notice",
        description="Winlink-related notices / bridging (varies by region).",
        example="help",
        tips="Winlink traffic usually uses RMS / Winlink Express. Message 'help' if the gate responds.",
    ),
]


def get_bot(callsign: str) -> AprsBot | None:
    c = callsign.strip().upper()
    for b in POPULAR_BOTS:
        if b.callsign.upper() == c or b.display_call.upper() == c:
            return b
    return None


def is_known_bot(callsign: str) -> bool:
    return get_bot(callsign) is not None
