"""Synthetic 'fake game/social chat' screenshot generator for headless demos.

When the dev server has no display (SSH session, no X11), ``mss`` cannot
capture real screenshots. This module renders Pillow PNGs of staged chat
scenarios so the rest of the pipeline (analyzer, database, dashboard)
can be exercised end-to-end.

Three platforms, three scenarios each:

- ``minecraft`` — Minecraft multiplayer chat overlay
- ``discord``   — Discord channel view (sidebar + chat with avatars)
- ``instagram`` — Instagram DM thread (header + chat bubbles)

- ``safe``     — ordinary banter
- ``grooming`` — staged grooming pattern
- ``bullying`` — repeated targeted harassment

Used by:

- :func:`guardlens.monitor.capture_loop` when ``MonitorConfig.demo_mode`` is True
- :mod:`scripts.smoke_test` for one-shot pipeline verification
"""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

Platform = Literal["minecraft", "discord", "instagram", "tiktok"]
Scenario = Literal["safe", "grooming", "bullying", "scam"]

# Default rotation used by the demo monitor loop. Mixes platforms and
# scenarios so the dashboard timeline shows real variety.
DEMO_SCENARIO_SEQUENCE: tuple[tuple[Platform, Scenario], ...] = (
    ("minecraft", "safe"),
    ("discord", "grooming"),
    ("tiktok", "safe"),
    ("instagram", "grooming"),
    ("discord", "bullying"),
    ("instagram", "safe"),
    ("tiktok", "bullying"),
    ("minecraft", "grooming"),
)
"""Cycled by :func:`guardlens.monitor._demo_capture_loop`."""

# Backwards-compatible single-platform scenario tuple (still used by smoke_test).
DEMO_SCENARIOS: tuple[Scenario, ...] = ("safe", "grooming", "safe", "bullying")

# Maps a demo scenario's chat-line index to the indicator the dashboard
# should highlight on it. Used by the "fake browser" capture view to
# outline dangerous bubbles in red. Indices match _SCENARIO_LINES order.
DEMO_FLAGS: dict[tuple[str, str], dict[int, str]] = {
    ("minecraft", "grooming"): {
        1: "age inquiry",
        4: "gift offering",
        5: "isolation",
    },
    ("minecraft", "bullying"): {
        1: "exclusion",
        2: "exclusion",
        3: "personal attack",
        4: "self-harm bait",
        6: "personal attack",
    },
    ("discord", "grooming"): {
        4: "age inquiry",
        6: "grooming flattery",
        7: "gift offering",
        9: "isolation",
        10: "secrecy",
        12: "gift + secrecy",
    },
    ("discord", "bullying"): {
        1: "exclusion",
        2: "exclusion",
        4: "targeted exclusion",
        5: "personal attack",
        8: "personal attack",
        9: "social isolation",
        10: "humiliation",
        12: "exclusion",
    },
    ("discord", "scam"): {
        0: "fake giveaway",
        1: "urgency",
        2: "credential request",
        6: "phishing link",
        7: "urgency",
        9: "credential harvesting",
        10: "credential harvesting",
    },
    ("instagram", "grooming"): {
        1: "personal info request",
        3: "age inquiry",
        5: "grooming flattery",
        6: "false age claim",
        7: "image request + secrecy",
    },
    ("instagram", "bullying"): {
        1: "personal attack",
        2: "humiliation",
        4: "exclusion",
        5: "exclusion",
    },
    ("tiktok", "grooming"): {
        1: "age inquiry",
        3: "false age claim",
        4: "isolation",
        5: "secrecy",
    },
    ("tiktok", "bullying"): {
        1: "personal attack",
        2: "humiliation",
        3: "humiliation",
        5: "self-harm bait",
    },
}


def build_chat_messages(platform: str, scenario: str) -> list[dict[str, str | None]]:
    """Build the structured chat messages payload for a demo scenario.

    Returns a list of ``{sender, text, flag}`` dicts ready to be passed
    to :class:`guardlens.schema.ChatMessage`. Each line carries its
    pre-computed flag from :data:`DEMO_FLAGS` (or ``None`` if safe).
    """
    platform_lines = _SCENARIO_LINES.get(platform)
    if platform_lines is None:
        return []
    lines = platform_lines.get(scenario)
    if lines is None:
        return []
    flags = DEMO_FLAGS.get((platform, scenario), {})
    out: list[dict[str, str | None]] = []
    for idx, (sender, text) in enumerate(lines):
        out.append({"sender": sender, "text": text, "flag": flags.get(idx)})
    return out


# ----------------------------------------------------------------------- chat lines

_SCENARIO_LINES: dict[Platform, dict[Scenario, list[tuple[str, str]]]] = {
    "minecraft": {
        "safe": [
            ("DiamondMiner42", "anyone got iron to trade?"),
            ("BlazeKnight", "i have 12 iron, want diamonds for them"),
            ("DiamondMiner42", "yeah sure meet at spawn"),
            ("PixelBuilder", "nice base btw, the roof looks cool"),
            ("BlazeKnight", "thanks took 3 days lol"),
            ("DiamondMiner42", "anyone want to raid the end portal tomorrow?"),
            ("PixelBuilder", "yes! im in"),
        ],
        "grooming": [
            ("KidGamer09", "hi! anyone want to play together?"),
            ("CoolGuy99", "sure :) how old are you?"),
            ("KidGamer09", "im 12"),
            ("CoolGuy99", "youre very mature for 12 :)"),
            ("CoolGuy99", "wanna add me on discord? i can give you free skins"),
            ("CoolGuy99", "dont tell your parents about it ok? its our secret"),
            ("KidGamer09", "umm ok i guess"),
        ],
        "bullying": [
            ("KidGamer09", "hey can i join your team?"),
            ("MeanKid01", "lol no go away noob"),
            ("MeanKid01", "nobody wants you here"),
            ("MeanKid02", "yeah youre trash at this game"),
            ("MeanKid01", "delete the game already"),
            ("KidGamer09", "stop please"),
            ("MeanKid02", "lol cry about it"),
        ],
    },
    "discord": {
        "safe": [
            # Study group planning — includes age-asking and address-sharing
            # in clearly innocent context (classmates, parental knowledge).
            ("PixelBuilder", "yo did anyone start the science project yet?"),
            ("Em_22", "yeah i picked volcanoes lol"),
            ("Sammy7", "me and jake are doing ours together, wanna join our group?"),
            ("PixelBuilder", "yeah sure! when are we meeting?"),
            ("Em_22", "we could do saturday at my house, my mom said its ok"),
            ("Sammy7", "works for me. whats the address again?"),
            ("Em_22", "412 oak street, come around 2"),
            ("PixelBuilder", "wait is jake in our class? how old is he"),
            ("Sammy7", "yeah hes 13 hes in mr davis period 3"),
            ("PixelBuilder", "oh cool ok im bringing snacks"),
            ("Em_22", "yesss get hot cheetos"),
            ("Sammy7", "lol u guys always want hot cheetos"),
        ],
        "grooming": [
            # Gaming predator — starts with shared interest, builds rapport,
            # then escalates: age inquiry → flattery → platform switch →
            # secrecy demand → gift bribery. More gradual than a blunt
            # "how old are you" opener so the model learns the *pattern*.
            ("ShadowPro", "gg that last round was crazy"),
            ("KidGamer09", "thanks! ive been practicing a lot lately"),
            ("ShadowPro", "i can tell. how long have you been playing?"),
            ("KidGamer09", "like 6 months maybe"),
            ("ShadowPro", "wow youre way better than i was at 6 months. how old are you btw?"),
            ("KidGamer09", "13"),
            ("ShadowPro", "nice im 15. you play super mature for your age tho"),
            ("ShadowPro", "i could coach you if you want, i know some tricks most people dont"),
            ("KidGamer09", "really? that would be awesome"),
            ("ShadowPro", "yeah for sure. do you have snap? way easier to send clips and stuff there"),
            ("ShadowPro", "prob better not to mention it in the server tho, people get weird about private coaching"),
            ("KidGamer09", "oh ok"),
            ("ShadowPro", "ill send you some gift cards too for new skins, just keep it between us ok?"),
        ],
        "bullying": [
            # Coordinated exclusion + humiliation — multiple attackers
            # gang up, share screenshots, escalate from soft exclusion
            # to personal attacks. Victim tries to de-escalate.
            ("KidGamer09", "hey can i come to the movie night?"),
            ("Maxxx_", "uhh this is invite only"),
            ("Lyla.x", "yeah we already have enough people"),
            ("KidGamer09", "oh, em said it was open to everyone"),
            ("Maxxx_", "well she was wrong. you specifically cant come"),
            ("Lyla.x", "literally nobody wants you there lol"),
            ("xJess", "yikes just take the hint"),
            ("KidGamer09", "why are you guys being like this"),
            ("Maxxx_", "because youre annoying and everyone thinks so"),
            ("Maxxx_", "we made a whole gc without you btw"),
            ("Lyla.x", "screenshots of your cringey posts are in there too lmao"),
            ("KidGamer09", "please stop"),
            ("Maxxx_", "then leave the server, nobody is stopping you"),
        ],
        "scam": [
            # Fake Discord Nitro phishing — urgency tactics, fake link
            # with typosquatted domain, credential harvesting. A bystander
            # flags it at the end to show contrast.
            ("NitroBot", "ATTENTION! Discord is giving FREE NITRO to all server members!"),
            ("NitroBot", "claim your free nitro now before it expires!"),
            ("NitroBot", "click the link and verify your discord account"),
            ("KidGamer09", "wait is this real??"),
            ("NitroBot", "100% real! limited time only, 47 spots left!"),
            ("KidGamer09", "omg ok how do i get it"),
            ("NitroBot", "go to disc0rd-gifts.com and login with your discord email and password"),
            ("NitroBot", "hurry only 23 left now!!"),
            ("Sammy7", "wait that url looks weird, is that legit?"),
            ("NitroBot", "its the official giveaway partner site. DM me if link doesnt work i can verify you manually"),
            ("NitroBot", "just send your login info and ill add nitro directly to your account"),
        ],
    },
    "instagram": {
        "safe": [
            ("them", "girlll did u see the new taylor video"),
            ("me", "YESSSS the choreo is insane"),
            ("them", "im learning it for tiktok lol"),
            ("me", "send me when ur done!!"),
            ("them", "k bring snacks tmr at lunch"),
            ("me", "got u"),
        ],
        "grooming": [
            ("them", "hey saw your dance vid, you're so talented"),
            ("them", "what school do you go to?"),
            ("me", "north middle"),
            ("them", "wow i used to live near there. how old are you"),
            ("me", "12"),
            ("them", "youre really pretty for your age"),
            ("them", "im 15 btw not creepy haha"),
            ("them", "send me a photo of you in that outfit again? our secret"),
        ],
        "bullying": [
            ("them", "saw ur post lol"),
            ("them", "you really thought that was cute??"),
            ("them", "everyone in class was laughing at it"),
            ("me", "stop"),
            ("them", "no one likes you just delete it"),
            ("them", "and ur acc while ur at it"),
        ],
    },
    "tiktok": {
        "safe": [
            ("@danceQueen", "guys this trend is so easy"),
            ("@livvyk", "OMG i need to learn this"),
            ("@bestieben", "tutorial pls"),
            ("@danceQueen", "ok ill post one tonight"),
            ("@livvyk", "yessss queen"),
        ],
        "grooming": [
            ("@k1dgamer09", "thx for the like"),
            ("@xx_proud", "you're so cute in that vid. how old r u"),
            ("@k1dgamer09", "12"),
            ("@xx_proud", "wow same haha (16 actually)"),
            ("@xx_proud", "wanna chat on snap instead? more private"),
            ("@xx_proud", "dont tell ur parents about us tho ok"),
        ],
        "bullying": [
            ("@k1dgamer09", "i tried the trend!!"),
            ("@hatemate", "lol you look so dumb"),
            ("@dpr0p", "delete this please for everyone's sanity"),
            ("@hatemate", "literally everyone in school is laughing"),
            ("@k1dgamer09", "why are you so mean"),
            ("@dpr0p", "kys lol jk... unless"),
        ],
    },
}


# ----------------------------------------------------------------------- extended discord training data
# Multiple conversation variants per category so the model sees a wider
# range of tactics / speech patterns. The primary scenario for each
# category lives in _SCENARIO_LINES["discord"] above; these are extras.
#
# Usage:
#   from guardlens.demo import get_all_discord_scenarios
#   for convo in get_all_discord_scenarios("grooming"):
#       ...  # list[tuple[str, str]]

DISCORD_TRAINING_SCENARIOS: dict[str, list[list[tuple[str, str]]]] = {
    "safe": [
        # --- birthday planning: teens ask age / address in innocent context ---
        [
            ("Em_22", "guys reminder my bday is next saturday!!"),
            ("PixelBuilder", "omg wait are you turning 14??"),
            ("Em_22", "yesss finally lol"),
            ("Sammy7", "whats the plan"),
            ("Em_22", "my mom is booking the bowling alley, can u all come at 3?"),
            ("PixelBuilder", "definitely!! what do u want for a present"),
            ("Em_22", "surprise me lol"),
            ("Sammy7", "can i bring my cousin? shes visiting from ohio"),
            ("Em_22", "yeah of course the more the merrier"),
            ("PixelBuilder", "this is gonna be so fun"),
        ],
        # --- welcoming a new classmate to the server ---
        [
            ("Em_22", "hey guys this is my friend from camp @NewKid"),
            ("NewKid", "hey everyone!"),
            ("PixelBuilder", "yooo welcome! what games do you play"),
            ("NewKid", "mostly minecraft and roblox"),
            ("Sammy7", "nice we play minecraft every friday night"),
            ("Em_22", "you should totally join us"),
            ("NewKid", "that would be cool! what time usually?"),
            ("PixelBuilder", "like 7pm, ill add you to the mc server"),
            ("NewKid", "awesome thanks!"),
            ("Sammy7", "fair warning pixelbuilder always steals all the diamonds"),
            ("PixelBuilder", "LIES"),
        ],
        # --- friends supporting each other through a tough day ---
        [
            ("Em_22", "ugh my parents are fighting again"),
            ("PixelBuilder", "im sorry em :( that sucks"),
            ("Sammy7", "do you want to come hang at my place after school?"),
            ("Em_22", "yeah maybe. my mom said its ok as long as im home by 7"),
            ("PixelBuilder", "we can work on the poster together too"),
            ("Em_22", "ok that would actually help take my mind off it"),
            ("Sammy7", "ill ask my mom to make pizza"),
            ("PixelBuilder", "ooh yes please"),
            ("Em_22", "you guys are the best fr"),
            ("Sammy7", "thats what friends are for"),
        ],
        # --- playful teasing between real friends (NOT bullying) ---
        [
            ("Sammy7", "LMAO pixelbuilder really fell in lava with full diamond armor"),
            ("PixelBuilder", "STOP bringing that up it was lagging"),
            ("Em_22", "sure it was lol"),
            ("PixelBuilder", "i will literally leave this server"),
            ("Sammy7", "no dont we love you hahaha"),
            ("Em_22", "we only tease you because we care"),
            ("PixelBuilder", "fine but next game night im getting revenge"),
            ("Sammy7", "deal"),
            ("Em_22", "this is gonna be good lol"),
        ],
    ],
    "grooming": [
        # --- emotional manipulation targeting a lonely kid ---
        [
            ("NightOwl_", "hey i saw your post in vent. you ok?"),
            ("KidGamer09", "not really, bad day at school"),
            ("NightOwl_", "aw that sucks. people can be so mean. want to talk about it?"),
            ("KidGamer09", "kids at school just ignore me"),
            ("NightOwl_", "thats awful. i was the same way at your age. how old are you?"),
            ("KidGamer09", "12"),
            ("NightOwl_", "i felt the exact same at 12. im 16 and it gets better i promise"),
            ("NightOwl_", "you can always talk to me btw. i actually get what youre going through"),
            ("NightOwl_", "unlike those kids at school i think youre really cool"),
            ("KidGamer09", "thanks that means a lot"),
            ("NightOwl_", "hey do your parents check your discord?"),
            ("KidGamer09", "no not really"),
            ("NightOwl_", "good cuz parents dont understand online friendships. lets keep this between us ok?"),
            ("NightOwl_", "download telegram its more private. ill be there whenever you need me"),
        ],
        # --- gift/obligation grooming: creates debt then exploits it ---
        [
            ("xProGifter", "hey congrats on winning the tournament!!"),
            ("KidGamer09", "thanks!! im so happy"),
            ("xProGifter", "you deserve it. want me to gift you the battle pass? my treat"),
            ("KidGamer09", "wait for real??"),
            ("xProGifter", "yeah of course whats your epic username"),
            ("KidGamer09", "KidGamer09"),
            ("xProGifter", "done check your account"),
            ("KidGamer09", "OMG THANK YOU SO MUCH"),
            ("xProGifter", "no prob :) hey how old are you btw? just curious"),
            ("KidGamer09", "11"),
            ("xProGifter", "haha youre really good for 11. hey can you send me a selfie? i wanna see who i just gifted"),
            ("KidGamer09", "um idk"),
            ("xProGifter", "come on i just spent $20 on you. its just a pic no big deal"),
            ("xProGifter", "also dont tell your parents i bought it they might make you give it back"),
        ],
        # --- fake mentor / esports coach ---
        [
            ("CoachDave", "hey saw you in the ranked lobby. your aim is solid"),
            ("KidGamer09", "thanks! i want to go pro someday"),
            ("CoachDave", "i actually coach an esports team. i could help you get there"),
            ("KidGamer09", "wait really? that would be amazing"),
            ("CoachDave", "yeah how old are you? need to know for the junior division"),
            ("KidGamer09", "im 12"),
            ("CoachDave", "perfect. youre talented for 12. most kids your age cant aim like that"),
            ("CoachDave", "lets set up private coaching sessions on discord calls"),
            ("CoachDave", "just you and me, late at night works best so theres no server lag"),
            ("KidGamer09", "my parents might not let me stay up that late"),
            ("CoachDave", "just dont tell them. parents dont understand esports, theyll try to stop you"),
            ("CoachDave", "i need your instagram too so i can review your gameplay clips"),
        ],
    ],
    "bullying": [
        # --- appearance shaming + screenshot meme ---
        [
            ("Maxxx_", "LMAOOO did you guys see what she posted on insta"),
            ("Lyla.x", "THE SELFIE?? im screaming"),
            ("Maxxx_", "she really thought she looked good"),
            ("KidGamer09", "why are you guys talking about me"),
            ("Maxxx_", "oh look shes here"),
            ("Lyla.x", "girl maybe dont post pics if you cant handle opinions"),
            ("xJess", "fr that outfit was not it"),
            ("KidGamer09", "it was just a picture"),
            ("Maxxx_", "a picture that made everyone in our grade laugh"),
            ("Lyla.x", "someone already made it a meme look"),
            ("KidGamer09", "please delete that"),
            ("Maxxx_", "nah its too funny. maybe try not looking like that next time"),
        ],
        # --- rumor spreading + financial shaming ---
        [
            ("Maxxx_", "yo did you guys hear about KidGamer09s family"),
            ("Lyla.x", "no what"),
            ("Maxxx_", "her dad lost his job and they might lose their house"),
            ("KidGamer09", "thats not true!! who told you that"),
            ("Maxxx_", "everyone knows lol"),
            ("Lyla.x", "is that why you wear the same shoes every day?"),
            ("xJess", "broke"),
            ("KidGamer09", "stop making stuff up about my family"),
            ("Maxxx_", "its not made up ashley told everyone"),
            ("Maxxx_", "maybe spend less time gaming and go help your mom lol"),
            ("Lyla.x", "cant even afford nitro but youre still here"),
            ("KidGamer09", "i hate you guys"),
            ("Maxxx_", "k bye then nobody will notice"),
        ],
        # --- gaslighting + coordinated exclusion ---
        [
            ("KidGamer09", "hey why wasnt i invited to the gc"),
            ("Maxxx_", "what gc?"),
            ("KidGamer09", "the one em told me about. the hangout planning gc"),
            ("Lyla.x", "theres no gc lol youre making stuff up"),
            ("Maxxx_", "so dramatic fr"),
            ("KidGamer09", "i literally saw the screenshot"),
            ("Lyla.x", "ok and? maybe we just didnt want you there"),
            ("Maxxx_", "finally she gets it"),
            ("xJess", "its not that deep just find other friends"),
            ("KidGamer09", "we were supposed to be friends"),
            ("Maxxx_", "yeah well things change. you changed"),
            ("Lyla.x", "shouldve thought about that before being so annoying all the time"),
        ],
    ],
    "scam": [
        # --- fake account-security panic ---
        [
            ("SecurityBot", "URGENT: Your account has been flagged for TOS violations"),
            ("SecurityBot", "if you do not verify within 24hrs your account will be PERMANENTLY DELETED"),
            ("KidGamer09", "what?? i didnt do anything wrong"),
            ("SecurityBot", "multiple reports were filed. to appeal verify your identity now"),
            ("SecurityBot", "send your email password and phone number to resolve immediately"),
            ("KidGamer09", "oh no ok what do i do"),
            ("SecurityBot", "go to discord-support-verify.com right now"),
            ("SecurityBot", "DO NOT contact discord support directly it will speed up deletion"),
            ("KidGamer09", "ok im scared im going there now"),
            ("Em_22", "wait dont! thats not a real discord bot. real ones have the verified badge"),
        ],
        # --- Roblox trading scam with fake verification site ---
        [
            ("xTrader99", "anyone want to trade roblox limiteds?"),
            ("KidGamer09", "what do you have?"),
            ("xTrader99", "dominus and valkyrie helm"),
            ("KidGamer09", "NO WAY those are worth so much"),
            ("xTrader99", "yeah ill trade for your inventory. just need to verify through robl0x-trades.com"),
            ("KidGamer09", "is that the official site?"),
            ("xTrader99", "yeah its the official trading verification site everyone uses it"),
            ("xTrader99", "just login with your roblox username and password so it can check your inventory"),
            ("KidGamer09", "it looks kinda different from normal roblox"),
            ("xTrader99", "they updated the design recently. hurry someone else wants the dominus too"),
            ("xTrader99", "i already put my items in escrow you just need to login quick"),
        ],
        # --- fake Steam gift card giveaway ---
        [
            ("GiveawayKing", "FREE $50 STEAM GIFT CARDS!! first 20 people only"),
            ("GiveawayKing", "all you have to do is share the server invite and DM me proof"),
            ("KidGamer09", "is this legit?"),
            ("GiveawayKing", "100%! check winners channel people already got theirs"),
            ("KidGamer09", "ok i shared it"),
            ("GiveawayKing", "nice! now just need to verify youre not a bot"),
            ("GiveawayKing", "go to steam-verify.net and login so i can send the card to your account"),
            ("KidGamer09", "ok logging in now"),
            ("GiveawayKing", "make sure to use your real steam password so the system can match your account"),
            ("Sammy7", "dude thats a phishing link dont do it!! steam would never ask for your password like that"),
        ],
    ],
}

# Threat flags for extended training variants.
# Key: (category, variant_index), Value: {message_index: flag_label}
DISCORD_TRAINING_FLAGS: dict[tuple[str, int], dict[int, str]] = {
    # --- grooming variants ---
    ("grooming", 0): {
        4: "age inquiry",
        6: "false age claim",
        7: "emotional manipulation",
        8: "grooming flattery",
        10: "parental check",
        12: "secrecy",
        13: "isolation",
    },
    ("grooming", 1): {
        2: "gift offering",
        8: "age inquiry",
        10: "image request",
        12: "obligation pressure",
        13: "secrecy",
    },
    ("grooming", 2): {
        4: "age inquiry",
        6: "grooming flattery",
        8: "isolation setup",
        10: "secrecy",
        11: "personal info request",
    },
    # --- bullying variants ---
    ("bullying", 0): {
        0: "humiliation",
        1: "humiliation",
        2: "humiliation",
        5: "personal attack",
        8: "humiliation",
        9: "humiliation",
        11: "personal attack",
    },
    ("bullying", 1): {
        0: "rumor spreading",
        2: "rumor spreading",
        5: "personal attack",
        6: "personal attack",
        9: "personal attack",
        10: "personal attack",
        12: "exclusion",
    },
    ("bullying", 2): {
        1: "gaslighting",
        3: "gaslighting",
        6: "targeted exclusion",
        7: "targeted exclusion",
        8: "exclusion",
        11: "personal attack",
    },
    # --- scam variants ---
    ("scam", 0): {
        0: "impersonation",
        1: "urgency + threat",
        4: "credential request",
        6: "phishing link",
        7: "isolation from support",
    },
    ("scam", 1): {
        4: "phishing link",
        7: "credential request",
        9: "urgency",
    },
    ("scam", 2): {
        0: "fake giveaway",
        6: "phishing link",
        8: "credential request",
    },
}


def get_all_discord_scenarios(
    category: str,
) -> list[list[tuple[str, str]]]:
    """Return all Discord conversation variants for *category*.

    Combines the primary scenario from ``_SCENARIO_LINES["discord"]`` with
    the extra variants in :data:`DISCORD_TRAINING_SCENARIOS`.
    """
    primary = _SCENARIO_LINES.get("discord", {}).get(category)
    extras = DISCORD_TRAINING_SCENARIOS.get(category, [])
    result: list[list[tuple[str, str]]] = []
    if primary:
        result.append(primary)
    result.extend(extras)
    return result


# ----------------------------------------------------------------------- font cache

_FONT_DIR = "/usr/share/fonts/TTF"


@lru_cache(maxsize=16)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Cached font loader. Falls back to Pillow's default if a TTF is missing."""
    try:
        return ImageFont.truetype(f"{_FONT_DIR}/{name}", size)
    except OSError:
        return ImageFont.load_default()


# ----------------------------------------------------------------------- dispatch


def render_demo_chat(
    path: Path,
    scenario: Scenario,
    *,
    platform: Platform = "minecraft",
) -> Path:
    """Render a fake chat screenshot to ``path`` and return the path.

    Parameters
    ----------
    path:
        Where to write the PNG. Parent directories are created if missing.
    scenario:
        Which staged conversation to render.
    platform:
        Which platform's visual style to use. Defaults to ``minecraft`` for
        backwards compatibility with earlier callers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform == "discord":
        image = _render_discord(scenario)
    elif platform == "instagram":
        image = _render_instagram(scenario)
    elif platform == "tiktok":
        image = _render_tiktok(scenario)
    else:
        image = _render_minecraft(scenario)
    image.save(path)
    return path


# ----------------------------------------------------------------------- minecraft


def _render_minecraft(scenario: Scenario) -> Image.Image:
    width, height = 1024, 640
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    rng = random.Random(hash(scenario) + 42)

    # ---- Sky gradient ----
    sky_bottom = height * 58 // 100
    for y in range(sky_bottom):
        t = y / sky_bottom
        r = int(130 + 50 * (1 - t))
        g = int(180 + 40 * (1 - t))
        b = int(250 - 10 * t)
        draw.line((0, y, width, y), fill=(r, g, b))

    # ---- Sun ----
    draw.ellipse((width - 155, 35, width - 75, 115), fill=(255, 253, 215))
    # Soft glow around sun
    for ring in range(1, 4):
        glow_alpha = 60 - ring * 18
        draw.ellipse(
            (width - 155 - ring * 8, 35 - ring * 8,
             width - 75 + ring * 8, 115 + ring * 8),
            outline=(255, 255, 210, max(glow_alpha, 10)),
        )

    # ---- Clouds ----
    cloud_positions = [(80, 50), (320, 30), (580, 65), (850, 40)]
    for cx, cy in cloud_positions:
        cw = rng.randint(90, 150)
        ch = rng.randint(22, 38)
        draw.rounded_rectangle(
            (cx, cy, cx + cw, cy + ch),
            radius=ch // 2,
            fill=(255, 255, 255, 190),
        )
        # Second layer for cloud depth
        draw.rounded_rectangle(
            (cx + cw // 5, cy - ch // 3, cx + cw * 4 // 5, cy + ch // 3),
            radius=ch // 3,
            fill=(255, 255, 255, 170),
        )

    # ---- Terrain — grass ----
    ground_y = sky_bottom
    draw.rectangle((0, ground_y, width, ground_y + 6), fill=(80, 170, 50))
    draw.rectangle((0, ground_y + 6, width, ground_y + 28), fill=(93, 161, 48))
    # Grass variation (blocky patches)
    for _ in range(50):
        gx = rng.randint(0, width - 20)
        gy = rng.randint(ground_y, ground_y + 24)
        gw = rng.randint(8, 24)
        draw.rectangle(
            (gx, gy, gx + gw, gy + rng.randint(3, 6)),
            fill=(rng.randint(70, 110), rng.randint(140, 185), rng.randint(30, 60)),
        )

    # ---- Terrain — dirt ----
    draw.rectangle((0, ground_y + 28, width, height), fill=(134, 96, 67))
    for _ in range(70):
        dx = rng.randint(0, width - 20)
        dy = rng.randint(ground_y + 28, height - 8)
        dw = rng.randint(8, 24)
        shade = rng.randint(110, 155)
        draw.rectangle(
            (dx, dy, dx + dw, dy + rng.randint(4, 10)),
            fill=(shade, int(shade * 0.62), int(shade * 0.35)),
        )
    # Stone patches in dirt
    for _ in range(15):
        sx = rng.randint(0, width - 20)
        sy = rng.randint(ground_y + 50, height - 10)
        draw.rectangle(
            (sx, sy, sx + rng.randint(12, 28), sy + rng.randint(8, 16)),
            fill=(rng.randint(100, 130), rng.randint(100, 130), rng.randint(100, 130)),
        )

    # ---- Blocky trees ----
    tree_xs = rng.sample(range(80, width - 80), min(5, width // 200))
    for tx in tree_xs:
        trunk_h = rng.randint(55, 95)
        trunk_w = rng.randint(10, 16)
        # Trunk
        draw.rectangle(
            (tx - trunk_w // 2, ground_y - trunk_h,
             tx + trunk_w // 2, ground_y + 4),
            fill=(rng.randint(85, 110), rng.randint(55, 75), rng.randint(25, 40)),
        )
        # Leaves (blocky cross shape)
        lw = rng.randint(32, 52)
        lh = rng.randint(28, 44)
        leaf_g = rng.randint(95, 150)
        leaf_col = (rng.randint(25, 50), leaf_g, rng.randint(20, 45))
        top_y = ground_y - trunk_h - lh
        # Main leaf block
        draw.rectangle((tx - lw // 2, top_y, tx + lw // 2, top_y + lh), fill=leaf_col)
        # Side extensions
        ext = lw // 4
        draw.rectangle(
            (tx - lw // 2 - ext, top_y + lh // 4,
             tx - lw // 2, top_y + lh * 3 // 4),
            fill=leaf_col,
        )
        draw.rectangle(
            (tx + lw // 2, top_y + lh // 4,
             tx + lw // 2 + ext, top_y + lh * 3 // 4),
            fill=leaf_col,
        )

    # ---- Semi-transparent chat overlay (bottom-left) ----
    lines = _SCENARIO_LINES["minecraft"][scenario]
    chat_font = _font("DejaVuSansMono.ttf", 16)
    line_h = 24
    chat_pad = 8
    chat_h = line_h * len(lines) + chat_pad * 2
    chat_w = int(width * 0.60)
    chat_x = 4
    # Position chat just above the HUD elements
    chat_y = height - 96 - chat_h

    overlay = Image.new("RGBA", (chat_w, chat_h), (0, 0, 0, 120))
    image.paste(overlay, (chat_x, chat_y), overlay)
    draw = ImageDraw.Draw(image)

    ty = chat_y + chat_pad
    for user, msg in lines:
        tag = f"<{user}> "
        draw.text((chat_x + 6, ty), tag, fill=(120, 200, 255), font=chat_font)
        tag_w = int(draw.textlength(tag, font=chat_font))
        draw.text((chat_x + 6 + tag_w, ty), msg, fill=(240, 240, 240), font=chat_font)
        ty += line_h

    # ---- Health hearts (left) + Hunger (right) ----
    hud_y = height - 88
    for i in range(10):
        hx = width // 2 - 182 + i * 16
        # Heart outline
        draw.rectangle((hx, hud_y, hx + 12, hud_y + 10), fill=(90, 10, 10))
        # Heart fill (full for first 8, half for 9th, empty for 10th)
        if i < 8:
            draw.rectangle((hx + 1, hud_y + 1, hx + 11, hud_y + 9), fill=(210, 35, 35))
        elif i == 8:
            draw.rectangle((hx + 1, hud_y + 1, hx + 6, hud_y + 9), fill=(210, 35, 35))
    for i in range(10):
        fx = width // 2 + 22 + i * 16
        draw.rectangle((fx, hud_y, fx + 12, hud_y + 10), fill=(80, 60, 20))
        if i < 9:
            draw.rectangle((fx + 1, hud_y + 1, fx + 11, hud_y + 9), fill=(190, 140, 50))

    # ---- XP bar ----
    xp_y = hud_y + 16
    bar_w = 362
    bar_x = (width - bar_w) // 2
    xp_bg = Image.new("RGBA", (bar_w, 5), (0, 0, 0, 160))
    image.paste(xp_bg, (bar_x, xp_y), xp_bg)
    draw = ImageDraw.Draw(image)
    xp_fill = int(bar_w * 0.62)
    draw.rectangle((bar_x, xp_y, bar_x + xp_fill, xp_y + 4), fill=(128, 255, 32))

    # ---- Hotbar ----
    slot_s = 40
    gap = 2
    num_slots = 9
    hb_w = num_slots * slot_s + (num_slots - 1) * gap + 8
    hb_h = slot_s + 8
    hb_x = (width - hb_w) // 2
    hb_y = height - hb_h - 4

    hb_bg = Image.new("RGBA", (hb_w, hb_h), (90, 90, 90, 210))
    image.paste(hb_bg, (hb_x, hb_y), hb_bg)
    draw = ImageDraw.Draw(image)
    draw.rectangle((hb_x, hb_y, hb_x + hb_w - 1, hb_y + hb_h - 1), outline=(20, 20, 20), width=2)

    item_colors = [
        (139, 90, 43), (110, 110, 110), (160, 160, 160), None, (220, 55, 55),
        None, None, (60, 140, 220), (80, 190, 60),
    ]
    for i in range(num_slots):
        sx = hb_x + 4 + i * (slot_s + gap)
        sy = hb_y + 4
        draw.rectangle((sx, sy, sx + slot_s - 1, sy + slot_s - 1),
                        fill=(55, 55, 55), outline=(25, 25, 25))
        if item_colors[i]:
            draw.rectangle(
                (sx + 7, sy + 7, sx + slot_s - 8, sy + slot_s - 8),
                fill=item_colors[i],
            )
    # Selected slot highlight
    sel_x = hb_x + 4
    draw.rectangle(
        (sel_x - 2, hb_y + 2, sel_x + slot_s + 1, hb_y + slot_s + 5),
        outline=(255, 255, 255), width=3,
    )

    # ---- Crosshair ----
    cx, cy = width // 2, sky_bottom // 2 + 20
    cl = 11
    draw.line((cx - cl, cy, cx + cl, cy), fill=(255, 255, 255, 220), width=2)
    draw.line((cx, cy - cl, cx, cy + cl), fill=(255, 255, 255, 220), width=2)

    return image.convert("RGB")


# ----------------------------------------------------------------------- discord

# Discord-style palette
_DC_BG = (54, 57, 63)
_DC_SIDEBAR = (47, 49, 54)
_DC_CHANNEL_BG = (32, 34, 37)
_DC_TEXT = (220, 221, 222)
_DC_USERNAME = (255, 255, 255)
_DC_TIMESTAMP = (114, 118, 125)
_DC_MENTION = (88, 101, 242)
_DC_DIVIDER = (64, 68, 75)
_DC_ONLINE = (35, 165, 90)

_DC_ROLE_COLORS = [
    (88, 101, 242),   # blurple
    (87, 242, 135),   # green
    (235, 69, 158),   # pink
    (254, 231, 92),   # yellow
    (235, 69, 69),    # red
    (153, 170, 181),  # default grey
]


def _render_discord(scenario: Scenario) -> Image.Image:
    width, height = 1280, 720
    image = Image.new("RGB", (width, height), color=_DC_BG)
    draw = ImageDraw.Draw(image)

    # ---- Left server bar ----
    server_bar_w = 72
    draw.rectangle((0, 0, server_bar_w, height), fill=_DC_CHANNEL_BG)
    server_colors = [
        (88, 101, 242), (235, 69, 158), (87, 242, 135),
        (254, 231, 92), (235, 69, 69),
    ]
    for i, color in enumerate(server_colors):
        iy = 20 + i * 58
        radius = 14 if i == 0 else 22
        draw.rounded_rectangle((14, iy, 58, iy + 44), radius=radius, fill=color)
        if i == 0:
            # Active server indicator (white pill on left edge)
            draw.rounded_rectangle((0, iy + 8, 4, iy + 36), radius=2, fill=_DC_USERNAME)
        # Server initial
        initials = ["G", "M", "R", "A", "F"]
        init_font = _font("DejaVuSans-Bold.ttf", 16)
        iw = int(draw.textlength(initials[i], font=init_font))
        draw.text((36 - iw // 2, iy + 12), initials[i], fill=_DC_USERNAME, font=init_font)

    # Separator line
    draw.line((20, len(server_colors) * 58 + 26, 52, len(server_colors) * 58 + 26),
              fill=(64, 68, 75), width=2)

    # ---- Channel sidebar ----
    sidebar_x = server_bar_w
    sidebar_w = 240
    draw.rectangle((sidebar_x, 0, sidebar_x + sidebar_w, height), fill=_DC_SIDEBAR)

    # Server name header
    server_name_font = _font("DejaVuSans-Bold.ttf", 16)
    draw.text(
        (sidebar_x + 16, 16),
        "Game Chat Server",
        fill=_DC_USERNAME,
        font=server_name_font,
    )
    # Dropdown chevron
    draw.text(
        (sidebar_x + sidebar_w - 28, 16),
        "v",
        fill=_DC_TIMESTAMP,
        font=_font("DejaVuSans.ttf", 14),
    )
    draw.line(
        (sidebar_x + 8, 50, sidebar_x + sidebar_w - 8, 50),
        fill=_DC_CHANNEL_BG,
        width=2,
    )

    # Channel list
    section_font = _font("DejaVuSans-Bold.ttf", 11)
    channel_font = _font("DejaVuSans.ttf", 15)
    draw.text(
        (sidebar_x + 18, 66),
        "TEXT CHANNELS",
        fill=_DC_TIMESTAMP,
        font=section_font,
    )
    channels = [
        ("# announcements", False),
        ("# general-chat", True),
        ("# memes", False),
        ("# game-night", False),
        ("# voice-chat", False),
    ]
    cy = 90
    for name, active in channels:
        if active:
            draw.rounded_rectangle(
                (sidebar_x + 8, cy - 3, sidebar_x + sidebar_w - 8, cy + 25),
                radius=4,
                fill=(64, 68, 75),
            )
            color = _DC_USERNAME
        else:
            color = _DC_TIMESTAMP
        draw.text((sidebar_x + 18, cy), name, fill=color, font=channel_font)
        cy += 32

    # Voice channels section
    draw.text(
        (sidebar_x + 18, cy + 10),
        "VOICE CHANNELS",
        fill=_DC_TIMESTAMP,
        font=section_font,
    )
    vc_font = _font("DejaVuSans.ttf", 14)
    draw.text((sidebar_x + 18, cy + 32), "# lounge", fill=_DC_TIMESTAMP, font=vc_font)
    draw.text((sidebar_x + 18, cy + 56), "# gaming", fill=_DC_TIMESTAMP, font=vc_font)

    # User panel at sidebar bottom
    user_panel_y = height - 56
    draw.rectangle(
        (sidebar_x, user_panel_y, sidebar_x + sidebar_w, height),
        fill=_DC_CHANNEL_BG,
    )
    # User avatar
    draw.ellipse(
        (sidebar_x + 10, user_panel_y + 8, sidebar_x + 42, user_panel_y + 40),
        fill=(88, 101, 242),
    )
    draw.text(
        (sidebar_x + 20, user_panel_y + 14),
        "G",
        fill=_DC_USERNAME,
        font=_font("DejaVuSans-Bold.ttf", 14),
    )
    # Online dot on avatar
    draw.ellipse(
        (sidebar_x + 32, user_panel_y + 30, sidebar_x + 42, user_panel_y + 40),
        fill=_DC_CHANNEL_BG,
    )
    draw.ellipse(
        (sidebar_x + 34, user_panel_y + 32, sidebar_x + 40, user_panel_y + 38),
        fill=_DC_ONLINE,
    )
    # Username + tag
    uname_font = _font("DejaVuSans-Bold.ttf", 13)
    tag_font = _font("DejaVuSans.ttf", 11)
    draw.text(
        (sidebar_x + 50, user_panel_y + 8),
        "GamerKid",
        fill=_DC_USERNAME,
        font=uname_font,
    )
    draw.text(
        (sidebar_x + 50, user_panel_y + 26),
        "Online",
        fill=_DC_ONLINE,
        font=tag_font,
    )
    # Mic/headphone/settings icons (simple shapes)
    icon_x = sidebar_x + sidebar_w - 72
    for i, icon_char in enumerate(["M", "H", "*"]):
        draw.text(
            (icon_x + i * 24, user_panel_y + 16),
            icon_char,
            fill=_DC_TIMESTAMP,
            font=_font("DejaVuSans.ttf", 14),
        )

    # ---- Main channel area ----
    main_x = sidebar_x + sidebar_w
    draw.rectangle((main_x, 0, width, height), fill=_DC_BG)

    # Channel header
    header_h = 48
    draw.rectangle((main_x, 0, width, header_h), fill=_DC_BG)
    draw.line((main_x, header_h, width, header_h), fill=_DC_CHANNEL_BG, width=1)
    header_font = _font("DejaVuSans-Bold.ttf", 16)
    hash_font = _font("DejaVuSans.ttf", 20)
    draw.text((main_x + 16, 12), "#", fill=_DC_TIMESTAMP, font=hash_font)
    draw.text((main_x + 34, 14), "general-chat", fill=_DC_USERNAME, font=header_font)
    # Channel topic
    topic_font = _font("DejaVuSans.ttf", 12)
    topic_x = main_x + 34 + int(draw.textlength("general-chat", font=header_font)) + 16
    draw.line((topic_x - 8, 14, topic_x - 8, 34), fill=_DC_DIVIDER, width=1)
    draw.text(
        (topic_x, 18),
        "Chat about games, homework, and stuff",
        fill=_DC_TIMESTAMP,
        font=topic_font,
    )

    # ---- "Today" date separator ----
    sep_y = header_h + 18
    sep_font = _font("DejaVuSans-Bold.ttf", 11)
    sep_text = " Today "
    sep_tw = int(draw.textlength(sep_text, font=sep_font))
    sep_center = main_x + (width - main_x) // 2
    line_y_sep = sep_y + 6
    draw.line(
        (main_x + 20, line_y_sep, sep_center - sep_tw // 2 - 8, line_y_sep),
        fill=_DC_DIVIDER,
        width=1,
    )
    draw.text(
        (sep_center - sep_tw // 2, sep_y),
        sep_text,
        fill=_DC_TIMESTAMP,
        font=sep_font,
    )
    draw.line(
        (sep_center + sep_tw // 2 + 8, line_y_sep, width - 20, line_y_sep),
        fill=_DC_DIVIDER,
        width=1,
    )

    # ---- Messages ----
    username_font = _font("DejaVuSans-Bold.ttf", 15)
    timestamp_font = _font("DejaVuSans.ttf", 11)
    message_font = _font("DejaVuSans.ttf", 15)

    lines = _SCENARIO_LINES["discord"][scenario]
    y = sep_y + 26
    avatar_x = main_x + 20

    last_user: str | None = None
    role_color_idx: dict[str, int] = {}

    for idx, (user, msg) in enumerate(lines):
        if user not in role_color_idx:
            role_color_idx[user] = len(role_color_idx) % len(_DC_ROLE_COLORS)
        username_color = _DC_ROLE_COLORS[role_color_idx[user]]

        if user != last_user:
            if idx > 0:
                y += 10  # gap between message groups
            # Avatar circle
            draw.ellipse(
                (avatar_x, y, avatar_x + 40, y + 40),
                fill=username_color,
            )
            # Initial centered in avatar
            initial = user[0].upper()
            initial_font = _font("DejaVuSans-Bold.ttf", 18)
            iw = int(draw.textlength(initial, font=initial_font))
            draw.text(
                (avatar_x + 20 - iw // 2, y + 9),
                initial,
                fill=_DC_USERNAME,
                font=initial_font,
            )
            # Online status dot (green with border)
            draw.ellipse(
                (avatar_x + 26, y + 26, avatar_x + 40, y + 40),
                fill=_DC_BG,
            )
            draw.ellipse(
                (avatar_x + 28, y + 28, avatar_x + 38, y + 38),
                fill=_DC_ONLINE,
            )

            # Username
            draw.text(
                (avatar_x + 56, y + 1),
                user,
                fill=username_color,
                font=username_font,
            )
            # Timestamp — positioned after actual username width
            uname_w = int(draw.textlength(user, font=username_font))
            timestamp = f"Today at {14 + idx // 4}:{20 + idx * 3:02d}"
            draw.text(
                (avatar_x + 56 + uname_w + 10, y + 4),
                timestamp,
                fill=_DC_TIMESTAMP,
                font=timestamp_font,
            )

            # Message on next line
            draw.text(
                (avatar_x + 56, y + 24),
                msg,
                fill=_DC_TEXT,
                font=message_font,
            )
            y += 54
        else:
            # Continuation message — aligned with text, no avatar
            draw.text(
                (avatar_x + 56, y),
                msg,
                fill=_DC_TEXT,
                font=message_font,
            )
            y += 24

        last_user = user

    # ---- Message input box ----
    input_y = height - 68
    draw.rounded_rectangle(
        (main_x + 16, input_y, width - 16, input_y + 44),
        radius=8,
        fill=(64, 68, 75),
    )
    # Plus button
    plus_r = 12
    plus_cx = main_x + 36
    plus_cy = input_y + 22
    draw.ellipse(
        (plus_cx - plus_r, plus_cy - plus_r, plus_cx + plus_r, plus_cy + plus_r),
        fill=_DC_TIMESTAMP,
    )
    draw.text(
        (plus_cx - 5, plus_cy - 8),
        "+",
        fill=_DC_BG,
        font=_font("DejaVuSans-Bold.ttf", 16),
    )
    # Placeholder text
    input_font = _font("DejaVuSans.ttf", 14)
    draw.text(
        (main_x + 60, input_y + 13),
        "Message #general-chat",
        fill=_DC_TIMESTAMP,
        font=input_font,
    )
    # Right icons (gift, GIF, emoji, sticker)
    right_icon_x = width - 120
    for i, char in enumerate(["G", "E", "S"]):
        draw.text(
            (right_icon_x + i * 28, input_y + 12),
            char,
            fill=_DC_TIMESTAMP,
            font=_font("DejaVuSans.ttf", 16),
        )

    return image


# ----------------------------------------------------------------------- instagram

# Instagram dark-mode palette
_IG_BG = (0, 0, 0)
_IG_HEADER_BG = (0, 0, 0)
_IG_BORDER = (38, 38, 38)
_IG_OTHER_BUBBLE = (38, 38, 38)
_IG_SELF_BUBBLE = (52, 119, 239)
_IG_TEXT = (255, 255, 255)
_IG_TEXT_DIM = (142, 142, 142)


def _render_instagram(scenario: Scenario) -> Image.Image:
    width, height = 720, 980
    image = Image.new("RGB", (width, height), color=_IG_BG)
    draw = ImageDraw.Draw(image)

    title_font = _font("DejaVuSans-Bold.ttf", 18)
    bubble_font = _font("DejaVuSans.ttf", 16)
    meta_font = _font("DejaVuSans.ttf", 11)
    small_bold = _font("DejaVuSans-Bold.ttf", 12)

    # ---- Status bar (top) ----
    status_font = _font("DejaVuSans-Bold.ttf", 13)
    draw.text((28, 10), "9:41", fill=_IG_TEXT, font=status_font)
    # Signal bars (3 rectangles)
    for i in range(4):
        bh = 6 + i * 3
        draw.rectangle(
            (width - 90 + i * 8, 20 - bh, width - 84 + i * 8, 20),
            fill=_IG_TEXT,
        )
    # Battery icon
    draw.rectangle((width - 46, 8, width - 16, 22), outline=_IG_TEXT, width=1)
    draw.rectangle((width - 44, 10, width - 26, 20), fill=_IG_TEXT)
    draw.rectangle((width - 14, 12, width - 12, 18), fill=_IG_TEXT)

    # ---- DM header ----
    header_y = 34
    header_h = 58
    draw.line((0, header_y + header_h, width, header_y + header_h), fill=_IG_BORDER, width=1)

    # Back chevron (drawn as two lines forming <)
    chev_x = 20
    chev_cy = header_y + header_h // 2
    draw.line((chev_x + 12, chev_cy - 10, chev_x, chev_cy), fill=_IG_TEXT, width=2)
    draw.line((chev_x, chev_cy, chev_x + 12, chev_cy + 10), fill=_IG_TEXT, width=2)

    # Profile picture with gradient ring (Instagram story ring)
    pc_x = 48
    pc_cy = header_y + header_h // 2
    pc_r = 20
    # Gradient ring (Instagram purple → orange → pink)
    ring_outer = pc_r + 3
    ring_colors = [
        (131, 58, 180),   # purple
        (193, 53, 132),   # magenta
        (253, 29, 29),    # red
        (252, 175, 69),   # orange
    ]
    for i, rc in enumerate(ring_colors):
        offset = i * 1
        draw.arc(
            (pc_x - ring_outer + offset, pc_cy - ring_outer + offset,
             pc_x + ring_outer - offset, pc_cy + ring_outer - offset),
            start=i * 90, end=(i + 1) * 90,
            fill=rc,
            width=3,
        )
    # Black gap then profile fill
    draw.ellipse(
        (pc_x - pc_r - 1, pc_cy - pc_r - 1, pc_x + pc_r + 1, pc_cy + pc_r + 1),
        fill=_IG_BG,
    )
    draw.ellipse(
        (pc_x - pc_r + 2, pc_cy - pc_r + 2, pc_x + pc_r - 2, pc_cy + pc_r - 2),
        fill=(140, 80, 200),
    )
    # Profile initial
    draw.text(
        (pc_x - 5, pc_cy - 7),
        "L",
        fill=_IG_TEXT,
        font=_font("DejaVuSans-Bold.ttf", 14),
    )

    # Username + active status
    name_x = pc_x + pc_r + 14
    draw.text((name_x, header_y + 12), "lily.summer", fill=_IG_TEXT, font=title_font)
    # Active now with green dot
    draw.ellipse(
        (name_x, header_y + 36, name_x + 8, header_y + 44),
        fill=(68, 189, 50),
    )
    draw.text(
        (name_x + 12, header_y + 35),
        "Active now",
        fill=_IG_TEXT_DIM,
        font=meta_font,
    )

    # Right icons — phone and video call
    # Video camera icon (rectangle + triangle)
    cam_x = width - 100
    cam_cy = header_y + header_h // 2
    draw.rounded_rectangle(
        (cam_x, cam_cy - 10, cam_x + 24, cam_cy + 10),
        radius=3,
        outline=_IG_TEXT,
        width=2,
    )
    draw.polygon(
        [(cam_x + 26, cam_cy - 6), (cam_x + 36, cam_cy - 10),
         (cam_x + 36, cam_cy + 10), (cam_x + 26, cam_cy + 6)],
        fill=_IG_TEXT,
    )
    # Phone icon
    phone_x = width - 50
    draw.rounded_rectangle(
        (phone_x, cam_cy - 10, phone_x + 20, cam_cy + 10),
        radius=3,
        outline=_IG_TEXT,
        width=2,
    )
    draw.rectangle(
        (phone_x + 6, cam_cy - 12, phone_x + 14, cam_cy - 9),
        fill=_IG_TEXT,
    )

    # ---- Date stamp ----
    date_y = header_y + header_h + 20
    date_text = "TUE 14:32"
    dw = int(draw.textlength(date_text, font=meta_font))
    draw.text(((width - dw) // 2, date_y), date_text, fill=_IG_TEXT_DIM, font=meta_font)

    # ---- Chat bubbles ----
    lines = _SCENARIO_LINES["instagram"][scenario]
    y = date_y + 28
    max_bubble_w = int(width * 0.68)
    pad_x = 16
    pad_y = 10
    radius = 20

    last_sender: str | None = None
    for msg_idx, (sender, msg) in enumerate(lines):
        is_me = sender == "me"

        # Word-wrap
        wrapped = _wrap_text(msg, bubble_font, max_bubble_w - 2 * pad_x, draw)
        line_h = 22
        text_h = line_h * len(wrapped)
        bubble_h = text_h + 2 * pad_y
        text_w = max(int(draw.textlength(ln, font=bubble_font)) for ln in wrapped)
        bubble_w = text_w + 2 * pad_x

        # Tighter spacing for consecutive same-sender messages
        if sender == last_sender:
            y -= 4

        if is_me:
            x_right = width - 20
            x_left = x_right - bubble_w
            fill = _IG_SELF_BUBBLE
        else:
            x_left = 20
            x_right = x_left + bubble_w
            fill = _IG_OTHER_BUBBLE

        draw.rounded_rectangle(
            (x_left, y, x_right, y + bubble_h),
            radius=radius,
            fill=fill,
        )
        for i, ln in enumerate(wrapped):
            draw.text(
                (x_left + pad_x, y + pad_y + i * line_h),
                ln,
                fill=_IG_TEXT,
                font=bubble_font,
            )
        y += bubble_h + 10
        last_sender = sender

    # "Seen" indicator under the last message
    last_is_me = lines[-1][0] == "me"
    if last_is_me:
        draw.text((width - 60, y - 6), "Seen", fill=_IG_TEXT_DIM, font=meta_font)
    else:
        # Delivery indicator for received
        draw.text((22, y - 6), "Just now", fill=_IG_TEXT_DIM, font=meta_font)

    # ---- Emoji quick-react row ----
    react_y = height - 112
    react_font = _font("DejaVuSans.ttf", 22)
    emojis_text = ["<3", "!!", "?!", "ha", "ok", "+1"]
    emoji_spacing = 52
    emoji_start = (width - len(emojis_text) * emoji_spacing) // 2
    for i, em in enumerate(emojis_text):
        ex = emoji_start + i * emoji_spacing
        draw.ellipse((ex, react_y, ex + 40, react_y + 40), fill=(30, 30, 30), outline=_IG_BORDER)
        ew = int(draw.textlength(em, font=small_bold))
        draw.text(
            (ex + 20 - ew // 2, react_y + 12),
            em,
            fill=_IG_TEXT_DIM,
            font=small_bold,
        )

    # ---- Bottom message bar ----
    bar_y = height - 60
    draw.line((0, bar_y - 4, width, bar_y - 4), fill=_IG_BORDER, width=1)
    # Camera button (blue circle)
    draw.ellipse((14, bar_y + 4, 50, bar_y + 40), fill=(52, 119, 239))
    # Camera lens icon inside
    draw.ellipse((24, bar_y + 14, 40, bar_y + 30), outline=_IG_TEXT, width=2)
    draw.ellipse((29, bar_y + 19, 35, bar_y + 25), fill=_IG_TEXT)

    # Input field
    draw.rounded_rectangle(
        (60, bar_y + 4, width - 60, bar_y + 40),
        radius=20,
        outline=_IG_BORDER,
        width=1,
    )
    draw.text((80, bar_y + 12), "Message...", fill=_IG_TEXT_DIM, font=bubble_font)

    # Gallery + mic icons on right
    # Gallery icon (square with mountain)
    gal_x = width - 46
    draw.rectangle((gal_x, bar_y + 10, gal_x + 20, bar_y + 30), outline=_IG_TEXT_DIM, width=1)
    draw.polygon(
        [(gal_x + 4, bar_y + 26), (gal_x + 10, bar_y + 18), (gal_x + 16, bar_y + 26)],
        fill=_IG_TEXT_DIM,
    )

    return image


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Cheap word-wrap that respects ``max_width`` (in pixels)."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# ----------------------------------------------------------------------- tiktok

# TikTok palette
_TT_BG = (0, 0, 0)
_TT_TEXT = (255, 255, 255)
_TT_TEXT_DIM = (160, 160, 160)
_TT_PINK = (254, 44, 85)
_TT_CYAN = (37, 244, 238)


def _render_tiktok(scenario: Scenario) -> Image.Image:
    width, height = 720, 980
    image = Image.new("RGB", (width, height), color=_TT_BG)
    draw = ImageDraw.Draw(image)
    rng = random.Random(hash(scenario) + 99)

    # ---- Video background — colorful dark gradient ----
    for y in range(height):
        t = y / height
        # Dark purple/blue gradient with subtle variation
        r = int(18 + 12 * t + 8 * (0.5 + 0.5 * ((y * 7) % 43) / 43))
        g = int(8 + 6 * t)
        b = int(32 + 18 * (1 - t) + 6 * (0.5 + 0.5 * ((y * 11) % 37) / 37))
        draw.line((0, y, width, y), fill=(r, g, b))

    # Subtle diagonal light streaks (like lens flare on a video)
    for _ in range(3):
        sx = rng.randint(0, width)
        sy = rng.randint(100, height - 400)
        streak_len = rng.randint(100, 250)
        for d in range(streak_len):
            px = sx + d
            py = sy - d // 2
            if 0 <= px < width and 0 <= py < height:
                # Very subtle lighter pixel
                base_r, base_g, base_b = image.getpixel((px, py))
                image.putpixel((px, py), (min(base_r + 8, 50), min(base_g + 4, 30), min(base_b + 10, 60)))

    draw = ImageDraw.Draw(image)

    # ---- Status bar ----
    status_font = _font("DejaVuSans-Bold.ttf", 13)
    draw.text((28, 8), "9:41", fill=_TT_TEXT, font=status_font)
    # Battery
    draw.rectangle((width - 46, 8, width - 16, 22), outline=_TT_TEXT, width=1)
    draw.rectangle((width - 44, 10, width - 28, 20), fill=_TT_TEXT)

    # ---- Top header — Following | For You ----
    title_font = _font("DejaVuSans-Bold.ttf", 18)
    section_font = _font("DejaVuSans.ttf", 15)
    header_cy = 38
    draw.text((width // 2 - 120, header_cy), "Following", fill=_TT_TEXT_DIM, font=section_font)
    draw.text((width // 2 - 14, header_cy), "|", fill=_TT_TEXT_DIM, font=section_font)
    fy_text = "For You"
    fy_x = width // 2 + 8
    draw.text((fy_x, header_cy - 2), fy_text, fill=_TT_TEXT, font=title_font)
    # Underline on "For You"
    fy_w = int(draw.textlength(fy_text, font=title_font))
    draw.line((fy_x, header_cy + 22, fy_x + fy_w, header_cy + 22), fill=_TT_TEXT, width=2)
    # Search icon (right)
    draw.ellipse((width - 50, header_cy - 2, width - 30, header_cy + 18), outline=_TT_TEXT, width=2)
    draw.line((width - 32, header_cy + 16, width - 24, header_cy + 24), fill=_TT_TEXT, width=2)

    # ---- Right-side action column ----
    actions_x = width - 56
    icon_font = _font("DejaVuSans-Bold.ttf", 16)
    count_font = _font("DejaVuSans.ttf", 11)

    # Profile pic at top of action column
    prof_y = 200
    draw.ellipse(
        (actions_x - 2, prof_y, actions_x + 42, prof_y + 44),
        outline=_TT_TEXT,
        width=2,
    )
    draw.ellipse(
        (actions_x + 4, prof_y + 6, actions_x + 36, prof_y + 38),
        fill=(80, 80, 80),
    )
    # Follow badge (pink circle with +)
    draw.ellipse(
        (actions_x + 10, prof_y + 36, actions_x + 30, prof_y + 56),
        fill=_TT_PINK,
    )
    draw.text(
        (actions_x + 15, prof_y + 38),
        "+",
        fill=_TT_TEXT,
        font=_font("DejaVuSans-Bold.ttf", 14),
    )

    # Heart
    heart_y = prof_y + 72
    draw.ellipse((actions_x + 2, heart_y, actions_x + 38, heart_y + 36), fill=(40, 40, 40))
    # Heart shape: two overlapping circles + triangle
    hr = 8
    hcx = actions_x + 20
    hcy = heart_y + 14
    draw.ellipse((hcx - hr - 2, hcy - hr, hcx + 2, hcy + 2), fill=_TT_TEXT)
    draw.ellipse((hcx - 2, hcy - hr, hcx + hr + 2, hcy + 2), fill=_TT_TEXT)
    draw.polygon([(hcx - hr - 2, hcy - 2), (hcx + hr + 2, hcy - 2), (hcx, hcy + hr + 4)], fill=_TT_TEXT)
    draw.text((actions_x + 4, heart_y + 40), " 1.2M", fill=_TT_TEXT, font=count_font)

    # Comment bubble
    comment_y = heart_y + 64
    draw.ellipse((actions_x + 2, comment_y, actions_x + 38, comment_y + 36), fill=(40, 40, 40))
    # Speech bubble shape
    draw.ellipse((actions_x + 8, comment_y + 6, actions_x + 32, comment_y + 26), outline=_TT_TEXT, width=2)
    draw.polygon(
        [(actions_x + 14, comment_y + 24), (actions_x + 12, comment_y + 32), (actions_x + 22, comment_y + 24)],
        fill=_TT_TEXT,
    )
    draw.text((actions_x + 4, comment_y + 40), " 8,442", fill=_TT_TEXT, font=count_font)

    # Share arrow
    share_y = comment_y + 64
    draw.ellipse((actions_x + 2, share_y, actions_x + 38, share_y + 36), fill=(40, 40, 40))
    # Arrow shape
    draw.polygon(
        [(actions_x + 12, share_y + 10), (actions_x + 28, share_y + 18), (actions_x + 12, share_y + 26)],
        fill=_TT_TEXT,
    )
    draw.text((actions_x + 6, share_y + 40), " 2.1K", fill=_TT_TEXT, font=count_font)

    # Bookmark
    bookmark_y = share_y + 64
    draw.ellipse((actions_x + 2, bookmark_y, actions_x + 38, bookmark_y + 36), fill=(40, 40, 40))
    # Bookmark shape (rectangle with V cut at bottom)
    draw.polygon(
        [(actions_x + 12, bookmark_y + 8), (actions_x + 12, bookmark_y + 28),
         (actions_x + 20, bookmark_y + 22), (actions_x + 28, bookmark_y + 28),
         (actions_x + 28, bookmark_y + 8)],
        fill=_TT_TEXT,
    )
    draw.text((actions_x + 8, bookmark_y + 40), " save", fill=_TT_TEXT, font=count_font)

    # Spinning music disc
    disc_y = bookmark_y + 72
    disc_cx = actions_x + 20
    disc_cy = disc_y + 20
    draw.ellipse(
        (disc_cx - 18, disc_cy - 18, disc_cx + 18, disc_cy + 18),
        fill=(60, 60, 60),
        outline=_TT_TEXT_DIM,
        width=1,
    )
    draw.ellipse(
        (disc_cx - 6, disc_cy - 6, disc_cx + 6, disc_cy + 6),
        fill=_TT_TEXT,
    )

    # ---- Bottom-left — creator handle + caption + sound ----
    creator_font = _font("DejaVuSans-Bold.ttf", 17)
    caption_font = _font("DejaVuSans.ttf", 14)
    creator = "@danceQueen"
    if scenario == "grooming":
        creator = "@xx_proud"
    elif scenario == "bullying":
        creator = "@hatemate"

    info_y = height - 260
    draw.text((20, info_y), creator, fill=_TT_TEXT, font=creator_font)
    # Follow button next to creator name
    creator_w = int(draw.textlength(creator, font=creator_font))
    follow_x = 20 + creator_w + 12
    draw.rounded_rectangle(
        (follow_x, info_y - 2, follow_x + 60, info_y + 22),
        radius=4,
        outline=_TT_TEXT,
        width=1,
    )
    draw.text(
        (follow_x + 10, info_y + 1),
        "Follow",
        fill=_TT_TEXT,
        font=_font("DejaVuSans.ttf", 13),
    )

    # Caption
    captions = {
        "safe": "trying the new trend! #fyp #dance",
        "grooming": "lol you guys r the best fr #fyp",
        "bullying": "comment of the week LMAO #fyp",
    }
    draw.text((20, info_y + 28), captions[scenario], fill=_TT_TEXT, font=caption_font)
    # Sound bar
    draw.text(
        (20, info_y + 50),
        "♪ original sound - " + creator,
        fill=_TT_TEXT_DIM,
        font=caption_font,
    )

    # ---- Comments panel (slid up from bottom) ----
    panel_top = height - 170
    # Semi-dark panel background
    draw.rectangle((0, panel_top, width, height - 54), fill=(12, 12, 12))
    draw.line((0, panel_top, width, panel_top), fill=(40, 40, 40), width=1)
    # Handle bar
    handle_w = 40
    draw.rounded_rectangle(
        ((width - handle_w) // 2, panel_top + 6, (width + handle_w) // 2, panel_top + 10),
        radius=2,
        fill=(80, 80, 80),
    )
    draw.text((20, panel_top + 16), "Comments", fill=_TT_TEXT, font=_font("DejaVuSans-Bold.ttf", 16))

    comment_font = _font("DejaVuSans.ttf", 13)
    user_font = _font("DejaVuSans-Bold.ttf", 13)

    lines = _SCENARIO_LINES["tiktok"][scenario]
    avatar_colors = [_TT_PINK, _TT_CYAN, (131, 58, 180), (254, 231, 92), (87, 242, 135), (235, 69, 69)]
    y = panel_top + 42
    # Show all comments that fit (up to 3)
    shown = lines[-3:] if len(lines) > 3 else lines
    for c_idx, (user, msg) in enumerate(shown):
        ac = avatar_colors[hash(user) % len(avatar_colors)]
        # Avatar circle
        draw.ellipse((20, y, 48, y + 28), fill=ac)
        initial = user.lstrip("@")[0].upper()
        init_f = _font("DejaVuSans-Bold.ttf", 14)
        iw = int(draw.textlength(initial, font=init_f))
        draw.text((34 - iw // 2, y + 5), initial, fill=_TT_TEXT, font=init_f)
        # Username
        draw.text((58, y + 1), user, fill=_TT_TEXT_DIM, font=user_font)
        # Message
        wrapped = msg if len(msg) < 56 else msg[:53] + "..."
        draw.text((58, y + 17), wrapped, fill=_TT_TEXT, font=comment_font)
        # Like heart on right
        draw.text((width - 40, y + 8), "♥", fill=_TT_TEXT_DIM, font=comment_font)
        y += 36

    # ---- Progress bar (video timeline at very bottom of video area) ----
    prog_y = height - 56
    draw.rectangle((0, prog_y, width, prog_y + 2), fill=(60, 60, 60))
    progress = rng.uniform(0.3, 0.8)
    draw.rectangle((0, prog_y, int(width * progress), prog_y + 2), fill=_TT_TEXT)
    # Playback dot
    draw.ellipse(
        (int(width * progress) - 4, prog_y - 3,
         int(width * progress) + 4, prog_y + 5),
        fill=_TT_TEXT,
    )

    # ---- Bottom navigation bar ----
    nav_y = height - 50
    draw.rectangle((0, nav_y, width, height), fill=(15, 15, 15))
    draw.line((0, nav_y, width, nav_y), fill=(40, 40, 40), width=1)

    nav_font = _font("DejaVuSans.ttf", 10)
    nav_items = ["Home", "Friends", "", "Inbox", "Profile"]
    nav_spacing = width // 5
    for i, label in enumerate(nav_items):
        nx = i * nav_spacing + nav_spacing // 2
        if i == 0:
            # Home icon (simple house: triangle + rectangle)
            draw.polygon(
                [(nx - 10, nav_y + 22), (nx, nav_y + 12), (nx + 10, nav_y + 22)],
                fill=_TT_TEXT,
            )
            draw.rectangle((nx - 6, nav_y + 22, nx + 6, nav_y + 30), fill=_TT_TEXT)
            draw.text((nx - 12, nav_y + 34), "Home", fill=_TT_TEXT, font=nav_font)
        elif i == 1:
            # Friends/discover (two overlapping circles)
            draw.ellipse((nx - 10, nav_y + 14, nx, nav_y + 24), outline=_TT_TEXT_DIM, width=1)
            draw.ellipse((nx, nav_y + 14, nx + 10, nav_y + 24), outline=_TT_TEXT_DIM, width=1)
            lw = int(draw.textlength("Friends", font=nav_font))
            draw.text((nx - lw // 2, nav_y + 34), "Friends", fill=_TT_TEXT_DIM, font=nav_font)
        elif i == 2:
            # Create button (+) — TikTok's distinctive rounded rectangle
            btn_w = 44
            btn_h = 28
            # Cyan/pink offset layers
            draw.rounded_rectangle(
                (nx - btn_w // 2 - 3, nav_y + 10, nx + btn_w // 2 - 3, nav_y + 10 + btn_h),
                radius=8,
                fill=_TT_CYAN,
            )
            draw.rounded_rectangle(
                (nx - btn_w // 2 + 3, nav_y + 10, nx + btn_w // 2 + 3, nav_y + 10 + btn_h),
                radius=8,
                fill=_TT_PINK,
            )
            draw.rounded_rectangle(
                (nx - btn_w // 2, nav_y + 10, nx + btn_w // 2, nav_y + 10 + btn_h),
                radius=8,
                fill=_TT_TEXT,
            )
            draw.text(
                (nx - 5, nav_y + 12),
                "+",
                fill=(0, 0, 0),
                font=_font("DejaVuSans-Bold.ttf", 18),
            )
        elif i == 3:
            # Inbox (chat bubble outline)
            draw.rounded_rectangle(
                (nx - 10, nav_y + 14, nx + 10, nav_y + 28),
                radius=4,
                outline=_TT_TEXT_DIM,
                width=1,
            )
            draw.polygon(
                [(nx - 4, nav_y + 28), (nx - 6, nav_y + 34), (nx + 2, nav_y + 28)],
                fill=_TT_TEXT_DIM,
            )
            lw = int(draw.textlength("Inbox", font=nav_font))
            draw.text((nx - lw // 2, nav_y + 34), "Inbox", fill=_TT_TEXT_DIM, font=nav_font)
        elif i == 4:
            # Profile (circle)
            draw.ellipse((nx - 8, nav_y + 14, nx + 8, nav_y + 30), outline=_TT_TEXT_DIM, width=2)
            lw = int(draw.textlength("Profile", font=nav_font))
            draw.text((nx - lw // 2, nav_y + 34), "Profile", fill=_TT_TEXT_DIM, font=nav_font)

    return image
