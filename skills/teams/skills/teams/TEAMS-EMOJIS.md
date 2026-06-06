# Teams Emoji Reference

Complete catalog of Microsoft Teams emoticon shortcodes for use in rich messages. Use these with the `:shortcode:` syntax (GitHub/Slack style) or `(shortcode)` syntax (Teams/Skype native) in message bodies passed to `send_message.py`.

> **Quick reference:** For the ~30 most frequently-used emojis, see the [Emoji Shortcodes section in SKILL.md](SKILL.md#emoji-shortcodes).

## How Emojis Render

Teams emojis are NOT Unicode characters. They render as animated/static images from the Teams CDN:

```
https://statics.teams.cdn.office.net/evergreen-assets/personal-expressions/v2/assets/emoticons/{id}/default/20_f.png
```

The `markdown_to_teams_html()` function in `utils.py` automatically converts `:shortcode:` and `(shortcode)` syntax to the proper HTML format:

```html
<span contenteditable="false" title="{title}" type="({id})" class="animated-emoticon-20-{id}" itemscope>
  <img itemscope itemtype="http://schema.skype.com/Emoji" itemid="{id}"
       src="https://statics.teams.cdn.office.net/.../emoticons/{id}/default/20_f.png"
       title="{title}" alt="{unicode}" style="width:20px;height:20px;">
</span>
```

## Mapped Shortcodes (utils.py EMOJI_MAP)

These shortcodes are mapped in `utils.py` and work with both `:name:` and `(name)` syntax:

### Faces & Expressions
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:smile:` | smile | 😊 |
| `:happy:` | happyface | 😀 |
| `:laugh:` / `:grinning:` | laugh | 😄 |
| `:grin:` | grinningfacewithsmilingeyes | 😁 |
| `:wink:` | wink | 😉 |
| `:blush:` | blush | 😊 |
| `:heart_eyes:` | inlove | 😍 |
| `:cool:` / `:sunglasses:` | cool | 😎 |
| `:surprised:` | surprised | 😮 |
| `:thinking:` / `:mmm:` | mmm | 🤔 |
| `:nerd:` / `:nerd_face:` | nerdy | 🤓 |
| `:sad:` / `:cry:` | sad | 😢 |
| `:angry:` | angryface | 😠 |
| `:pensive:` | pensive | 😔 |
| `:confused:` | confused | 😕 |
| `:expressionless:` | expressionless | 😑 |
| `:sleepy:` | sleepy | 😴 |
| `:puke:` | puke | 🤮 |
| `:skull:` | skull | 💀 |
| `:ghost:` | ghost | 👻 |
| `:devil:` | devil | 😈 |
| `:angel:` | angel | 😇 |
| `:shrug:` | shrug | 🤷 |
| `:facepalm:` | facepalm | 🤦 |
| `:salute:` | salute | 🫡 |
| `:melting:` | meltingface | 🫠 |

### Hand Gestures
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:thumbsup:` / `:+1:` / `:like:` / `:yes:` | yes | 👍 |
| `:thumbsdown:` / `:-1:` / `:no:` | no | 👎 |
| `:clap:` | clap | 👏 |
| `:muscle:` | muscle | 💪 |
| `:pray:` / `:praying:` | praying | 🙏 |
| `:wave:` / `:hi:` | hi | 👋 |
| `:handshake:` | handshake | 🤝 |
| `:ok_hand:` | ok | 👌 |
| `:victory:` | victory | ✌️ |
| `:punch:` | punch | 👊 |
| `:point_up:` | pointupindex | ☝️ |
| `:vulcan:` | vulcansalute | 🖖 |
| `:heart_hands:` | hearthands | 🫶 |
| `:finger_heart:` | fingerheart | 🫰 |

### Hearts & Love
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:heart:` / `:red_heart:` | heart | ❤️ |
| `:broken_heart:` | brokenheart | 💔 |
| `:sparkling_heart:` | sparklingheart | 💖 |
| `:two_hearts:` | twohearts | 💕 |
| `:growing_heart:` | growingheart | 💗 |
| `:heart_on_fire:` | heartonfire | ❤️‍🔥 |
| `:rainbow_heart:` | rainbowheart2 | 🏳️‍🌈 |

### Objects & Symbols
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:rocket:` / `:launch:` | launch | 🚀 |
| `:star:` | star | ⭐ |
| `:sparkles:` | sparkler | ✨ |
| `:trophy:` | trophy | 🏆 |
| `:medal:` / `:gold_medal:` | goldmedal | 🥇 |
| `:target:` / `:dart:` | target | 🎯 |
| `:bulb:` / `:idea:` / `:light_bulb:` | idea | 💡 |
| `:bell:` | bell | 🔔 |
| `:gift:` | gift | 🎁 |
| `:bomb:` | bomb | 💣 |
| `:lock:` | 1f512_locked | 🔒 |
| `:key:` | oldkey | 🔑 |
| `:link:` / `:chain:` | 1f517_linksymbol | 🔗 |
| `:gear:` | 2699_gear | ⚙️ |
| `:wrench:` | 1f527_wrench | 🔧 |
| `:hammer:` | 1f528_hammer | 🔨 |
| `:shield:` | 1f6e1_shield | 🛡️ |
| `:camera:` | camera | 📷 |
| `:phone:` | phone | 📱 |
| `:computer:` | computer | 💻 |
| `:headphones:` | headphones | 🎧 |
| `:money:` / `:cash:` | cash | 💰 |
| `:recycle:` | recycle | ♻️ |
| `:magic_wand:` | magicwand | 🪄 |
| `:crystal_ball:` | 1f52e_crystalball | 🔮 |
| `:zap:` / `:electric:` / `:lightning:` | 26a1_highvoltagesign | ⚡ |
| `:plug:` / `:electric_plug:` | 1f50c_electricplug | 🔌 |
| `:battery:` | lowbattery | 🪫 |
| `:wifi:` | wifi | 📶 |
| `:globe:` / `:world:` | 1f30d_earthglobeeuropeafrica | 🌍 |
| `:brain:` | 1f9e0_brain | 🧠 |
| `:arrow_right:` | 27a1_blackrightwardsarrow | ➡️ |

### Communication & Documents
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:email:` / `:envelope:` | loveletter | 💌 |
| `:memo:` | 1f4dd_memo | 📝 |
| `:clipboard:` | 1f4cb_clipboard | 📋 |
| `:book:` | 1f4d3_notebook | 📖 |
| `:calendar:` / `:date:` | spiralcalendar | 📅 |
| `:chart:` / `:bar_chart:` | 1f4ca_barchart | 📊 |
| `:speech_bubble:` | speechbubble | 💬 |
| `:file_folder:` | 1f4c1_filefolder | 📁 |
| `:floppy_disk:` | 50th_floppy | 💾 |
| `:pencil:` | 270f_pencil | ✏️ |
| `:mag:` / `:search:` | 1f50d_magnifiertiltedleft | 🔍 |

### Celebration
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:tada:` / `:party:` / `:fireworks:` / `:confetti:` | fireworks | 🎉 |
| `:champagne:` | champagne | 🍾 |
| `:cheers:` | cheers | 🍻 |
| `:cake:` | cake | 🎂 |
| `:balloon:` | 1f388_balloon | 🎈 |

### Nature & Weather
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:sun:` | sun | ☀️ |
| `:rainbow:` | rainbow | 🌈 |
| `:snowflake:` | snowflake | ❄️ |
| `:rain:` | rain | 🌧️ |
| `:flower:` | flower | 🌸 |
| `:rose:` | rose | 🌹 |
| `:tree:` | deciduoustree | 🌳 |
| `:cactus:` | cactus | 🌵 |

### Animals
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:dog:` | dog | 🐶 |
| `:cat:` | cat | 🐱 |
| `:monkey:` | monkey | 🐵 |
| `:penguin:` | penguin | 🐧 |
| `:unicorn:` | unicornhead | 🦄 |
| `:butterfly:` | butterfly | 🦋 |
| `:bee:` | bee | 🐝 |
| `:snake:` | snake | 🐍 |
| `:eagle:` | 1f985_eagle | 🦅 |

### Food & Drink
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:coffee:` | coffee | ☕ |
| `:pizza:` | pizzaslice | 🍕 |
| `:burger:` | burger | 🍔 |
| `:fries:` | fries | 🍟 |
| `:beer:` | beer | 🍺 |
| `:wine:` | redwine | 🍷 |
| `:tea:` | chai | 🍵 |
| `:cookie:` | cookies | 🍪 |
| `:avocado:` | avocadolove | 🥑 |

### Status Indicators
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:check:` / `:white_check_mark:` | 2705_whiteheavycheckmark | ✅ |
| `:x:` / `:cross:` | 274c_crossmark | ❌ |
| `:warning:` | 26a0_warningsign | ⚠️ |
| `:stop:` | stopsign | 🛑 |
| `:construction:` / `:building_construction:` | 1f6a7_constructionsign | 🚧 |
| `:hourglass:` | 231b_hourglassdone | ⏳ |
| `:arrow_right:` | 27a1_blackrightwardsarrow | ➡️ |

### Miscellaneous
| Shortcode | Teams ID | Renders As |
|-----------|----------|------------|
| `:robot:` | coolrobot | 🤖 |
| `:alien:` | 1f47d_extraterrestrialalien | 👽 |
| `:ninja:` | ninja | 🥷 |
| `:detective:` | detective | 🕵️ |
| `:mag:` / `:search:` | 1f50d_magnifiertiltedleft | 🔍 |

---

## All Teams Emoticon IDs (691 Skype-Style Shortcodes)

These are all the Skype-style emoticon IDs available in the Teams CDN. To use one that isn't in the `EMOJI_MAP`, add an entry to `EMOJI_MAP` in `utils.py`, or use `build_emoji_html(id, title, alt)` directly.

```
50th_50, 50th_butterfly, 50th_camera, 50th_card, 50th_cd, 50th_chess,
50th_clippy, 50th_cloud, 50th_cursor, 50th_explorer, 50th_floppy,
50th_folder, 50th_mail, 50th_msnbutterfly, 50th_paint, 50th_paintbucket,
50th_rainbow, 50th_search, 50th_slate, 50th_smile, 50th_sun, 50th_tree,
50th_win98, accordion, ambulance, americainhand, americanfootball,
anatomicalheart, angel, angryface, apple, asiaaustraliainhand, aubergine,
avocadolove, banana, bartlett, baseball, basketball, batsmile, beans, beaver,
bee, beer, beetle, bell, bellpepper, bicycle, bike, birdblack, bison,
bitinglip, blackcat, blueberries, blush, bomb, boomerang, bottlefeeding,
bouncing_ball, bow, bowing, bowlingball, boxingglove, breastfeeding,
brokenchain8, brokenheart, bronzemedal, brownmushroom4, bubbles, bubbletea,
bucket, bug, bunny, bunnyhug, buoy, burger, butterfly, cactus, cactuslove,
cake, cakeslice, call, camera, car, carpentrysaw, cash, cat, chai, champagne,
cheers, cheese, cherries, cherryblossom, chickenleg, cigarette, clap,
clappinghands, climber, cockroach, coffee, coin, computer, confused,
construction_worker, cookies, cool, coolcat, cooldog, coolkoala, coolmonkey,
coolrobot, coral, cricket, cricketbatandball, croissant, crossedfingers,
crutch, cupcake, cwl, dance, deciduoustree, desert, detective, devil,
diagonalmouth, diamond, disappointed, disguisedface, dodo, dog, doh, dolphin,
donkey, dottedlineface, dracula, dream, drink, dropthemic, dull, eightball,
electriccar, elephant, elevator, elf, emo, equals, europeafricainhand,
evergreentree, exclamationquestionmark, expressionless, eyeinspeechbubble,
faceexhaling, faceholdingbacktears, faceinclouds, facepalm,
facewithspiraleyes, fairy, fallingleaf, fan, fearful, feather, fingerheart,
fingerscrossed, fireworks, fish, flaginhole, flatbread, flower, flute, fly,
fondue, foxhug, fries, frowning, games, ghost, gift, ginger, glitterball,
goldmedal, golfer, goodluck, goose, gottarun, gran, grapes,
grinningfacewithsmilingeyes, growingheart, guard, guitar, hairpick, hamsa,
handovermouth, handshake, happy_person_raising_one_hand, happyface, headbang,
headphone, headphones, headshakinghorizontally2, headshakingvertically2,
headstone, hearnoevil, heart, heartblack, heartblue, heartbrown,
hearteyescat, hearteyesdog, hearteyeskoala, hearteyesmonkey, hearteyesrobot,
heartgreen, heartgrey, hearthands, heartlightblue, heartonfire, heartorange,
heartpink, heartpurple, heartwhite, heartyellow, hedgehoghug, hendance, hero,
hi, holdon, holidayspirit, hook, horse_racing, house, hug, hungover, hut,
hyacinth, idcard, idea, ill, inlove, island, jar, jellyfish,
keycapdigiteight, keycapdigitfive, keycapdigitfour, keycapdigitnine,
keycapdigitone, keycapdigitseven, keycapdigitsix, keycapdigitthree,
keycapdigittwo, keycapdigitzero, keycapnumberasterisk, keycapnumbersign,
khanda, kickscooter, kiss, knot, koala, lacrosse, ladder, ladyvampire, lamb,
laugh, laughcat, laughdog, laughkoala, laughmonkey, laughrobot, launch,
leftwardshand, lemon, like, lime4, lion, lips, lipssealed, lipstick, lizard,
longdrum, lotus, lotus_position, loveletter, lowbattery, lungs, magicwand,
mammoth, man_bouncing_ball, man_cartwheeling, man_climbing,
man_construction_worker, man_deaf, man_detective, man_fairy, man_frowning,
man_gesturing_not_ok, man_gesturing_ok, man_getting_face_massage,
man_getting_haircut, man_guard, man_in_manual_wheelchair,
man_in_motorized_wheelchair, man_in_suit_levitating, man_kneeling,
man_pouting, man_probing_cane, man_raising_hand, man_singer, man_steam_room,
man_super_villain, man_tipping_hand, man_wearing_turban,
man_with_chinese_cap, manartist, manastronaut, manbeard, manblondhair,
manbottlefeeding, manchef, manelf, manfacepalming, manfarmer, manfirefighter,
mangenie, mangolfing, manhealthworker, maninlotusposition, manintuxedo,
manjudge, manjuggling, manliftingweights, manmechanic, manmountainbiking,
manpilot, manplayinghandball, manplayingwaterpolo, manpoliceofficer,
manrowingboat, manscientist, manshrug, manstanding, manstudent, mansuperhero,
mansurfer, manswimming, manteacher, mantechie, manwalking, manwelder,
manwithveil, manzombie, maracas, matreshka, meltingface, mendingheart,
mermaid, merman, merperson, militaryhelmet, mirror, mmm, monkey, moose,
mother_christmas, motorbike, mousetrap, movember, movie, muscle, music,
mxclaus, nerdy, nest, nestwitheggs, ninja, no, nod, nonbinarystanding,
noodles, octopus, officeworkerfemale, officeworkermale, ok, oldkey, oldwoman,
olive, orange, orangutanscratching, oreo, oreoyum, palmdownhand, palmtree,
palmuphand, panda, peach, peapod, peekingeye, penguin, penguinkiss, pensive,
peoplehugging, person, person_deaf, person_getting_haircut, person_in_bed,
person_tipping_hand, personartist, personastronaut, personchef, personcrown,
persondeveloper, personfarmer, personfirefighter, personhealthworker,
personintuxedo, personjudge, personjuggling, personkneelingfacingright2,
personmanualwheelchairright2, personmechanic, personmotorwheelchairright2,
personofficeworker, personpilot, personrowingboat, personrunningfacingright2,
personscientist, personsinger, personsuperhero, personswimming, personteacher,
personwalkingfacingright2, personwelder, personwhitehair,
personwithprobingcane, personwithveil, personzombie, phoenix3, phone,
pickuptruck, pie, pig, pinata, pinchedfingers, pineapple, pizzaslice,
placard, plane, plunger, pointdownindex, pointleftindex, pointrightindex,
pointupindex, poke, polarbear, police_officer, policecar, poop, pottedplant,
pour, pouting_face, praying, pregnant, pregnantman, prince, princess, puke,
pumpkin, punch, pushleft, pushright, racoon, rain, rainbow, rainbowheart2,
rainbowsmile, raisedfist, recycle, redwine, reindeer, reminderribbon,
ribbonred, rickshaw, rightwardshand, ring, rollerskate, rose, rugbyball,
runner, running, sad, sadcat, saddog, sadkoala, sadmonkey, sadrobot, salute,
sandcastle, santa, sarcastic, scooter, screwdriver, seal, seedling,
seenoevil, selfie, selfiehand, sewingneedle, shake, shaking, shivering,
shopping, shrug, silvermedal, skate, skier, skull, sleepingface, sleepy,
slide, sloth, smile, smilebaby, smileboy, smilecat, smiledog, smileeyes,
smilegirl, smileman, smilemonkey, smilerobot, smilewoman, smirk, snail,
snake, snegovik, snowangel, snowboarder, snowflake, snowmanwithoutsnow,
soccerball, sparkler, sparklingheart, speaknoevil, speechbubble, spider,
spiralcalendar, spoutingwhale, squintingfacewithtongue, star,
statueofliberty, steam_room, steamtrain, stingray, stone, stopsign,
strawberry, student, sun, sunflower, support, surprised, swear, sweat,
sweatgrinning, tamale, target, taxi, teapot, telephonereceiver, tennisball,
thanks, thewave1, thewave2, thewave3, thewave4, thewave5, thongsandal, tmi,
toilet, tongueout, toothbrush, tortoise, transgendersymbol, trex, troll,
trophy, tropicalfish, truck, ttm, tulip, turkey, twohearts, umbrella,
unicornhead, vampire, vegetablegarden, veryconfused, victory, vulcansalute,
wait, wasntme, watermelon, weary, weight_lifter, werewolfhowl, wfh, whale,
wheel, wifi, wiltedflower, window, windturbine, wing, wingleft, wink,
winktongueout, wizard, woman_bouncing_ball, woman_cartwheeling,
woman_climbing, woman_construction_worker, woman_deaf, woman_detective,
woman_elf, woman_fairy, woman_getting_haircut, woman_golfer, woman_guard,
woman_in_manual_wheelchair, woman_in_motorized_wheelchair, woman_juggling,
woman_kneeling, woman_mountain_biking, woman_playing_handball,
woman_playing_water_polo, woman_probing_cane, woman_rowing_boat, woman_singer,
woman_steam_room, woman_super_villain, woman_swimmer, woman_walking,
woman_weight_lifter, woman_with_head_scarf, womanartist, womanastronaut,
womanbath, womanbeard, womanblondhair, womanchef, womancurlyhair,
womandeveloper, womanfacepalming, womanfarmer, womanfencer, womanfirefighter,
womanfootball, womanfrowning, womangenie, womangesturingno, womangesturingok,
womanhealthworker, womanintuxedo, womanjudge, womanmage, womanmechanic,
womanpilot, womanpoliceofficer, womanpouting, womanpregnant,
womanraisinghand, womanridingbike, womanscientist, womanshrug, womanstanding,
womanstudent, womansurfer, womanteacher, womantippinghand,
womanwearingturban, womanwelder, womanwhitehair, womanwithveil, wonder, wood,
worm, worry, xmastree, xray, yes, yoga, zombie
```

Additionally, there are **935 Unicode-based emoticon IDs** (format: `{codepoint}_{name}`, e.g. `1f603_grinningfacewithbigeyes`) available on the Teams CDN. These follow the pattern:

```
https://statics.teams.cdn.office.net/evergreen-assets/personal-expressions/v2/assets/emoticons/1f603_grinningfacewithbigeyes/default/20_f.png
```

To use a Unicode-based emoji, use `build_emoji_html("1f603_grinningfacewithbigeyes", "Grinning Face", "😃")` directly in code.
