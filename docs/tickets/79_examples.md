### Highlight Format

```yaml
> [!quote] Tom Holland
> - And the thing is, Dominic, isn't it, that the genius of Bowie is that he is superb at, you know, his chameleon-esque qualities, at finding characters who do reflect the zeitgeist.

> [!quote] Dominic Sandbrook
> - Yeah, absolutely right. He does reflect the zeitgeist.

> [!quote] Tom Holland
> - And I think a little bit like the Fawlty Towers rant that you did last week.

> [!quote] Dominic Sandbrook
> - It's a nice window into the sort of nightmares of the British imagination in the mid 70s. 
> - I mean, the thing about Hitler being better than Jagger.
```

### Current known hl formats

CURRENT FORMAT:

```bash
**<hl heading>**

- <bullet point 1>
- <bullet point 2>

Transcript:
<speaker>
<quote>
```


OLDER FORMATS:

1 - without key takeaways

```bash
<hl heading>

Transcript:
<speaker>
<quote>
```

2 - with key takeaways

```bash
<hl heading>

Key takeaways:
- <bullet 1>
- ...
- <bullet x>

Transcript:
<speaker>
<quote>
```
### Front matter sample from clippings

---
title: "Iran’s youth hoped for revolution. Instead they waded through blood"
source: "https://www.thetimes.com/world/middle-east/article/life-in-iran-protests-trump-us-war-hhgbrd5s7"
author:
  - "[[Catherine Philp]]"
published: 2026-07-29
created: 2026-07-30
description: "Reza joined protests in Mashhad in January. Now, traumatised by state violence, his only wish is to escape as Trump’s war continues"
tags:
  - "clippings"
site: "[[The Times]]"
---

### Transcript samples:

Single speaker:
[(0, 'Dominic Sandbrook'), (1, 'Callaghan is brilliant at...')]
[(0, 'Daniel Finkelstein'), (1, "Profoundly between restore... ")]
[(0, 'Daniel Finkelstein'), (1, "Tony Blair has...")]

Multispeaker
[(0, 'Sally Morgan'), (1, "Look, it's not helpful... "), (2, 'Hugo Rifkind'), (3, "But it's an election that will...")]

[(0, 'Dominic Sandbrook'), (1, "He literally ends up being banished to present..."), (2, 'Tom Holland'), (3, "Yeah, Harold Wilson's birthday, odious."), (4, 'Dominic Sandbrook'), (5, "Odious. In his diary, he wrote afterwards..."), (6, 'Tom Holland'), (7, "That may not even be true of...")]

[(0, 'Dominic Sandbrook'), (1, "I guess i'll..."), (2, 'Tom Holland'), (3, "But he, I mean, maybe he's...  "), (4, 'Dominic Sandbrook'), (5, "...")]

[(0, 'Dominic Sandbrook'), (1, "Now, in the 70s..."), (2, 'Tom Holland'), (3, 'Something that will...'), (4, 'Dominic Sandbrook'), (5, "Newspaper verdict on uh..."), (6, 'Tom Holland'), (7, "He's already been Chancellor..."), (8, 'Dominic Sandbrook'), (9, "The Grand Slam..."), (10, 'Tom Holland'), (11, "And reassuring he has"), (12, 'Dominic Sandbrook'), (13, "Thing he does in the he wears"), (14, 'Tom Holland'), (15, 'God, I mean, imagine '), (16, 'Dominic Sandbrook'), (17, "That would s")]

[(0, 'Tom Holland'), (1, 'And at that stage, that was the quickest fall in the pounds value in history. But presumably, this is seen on the left of the Labour Party as the names of Zurich kicking in, international finance doing its worst.'), (2, 'Dominic Sandbrook'), (3, "Exactly right. So if you're on the left of the Labour Party, if you're Tony Benn, you look at this and you say, well this is international capitalism conspiring against British socialism you know that's You basically say um")]


### Episode AI Notes example 

```
"Episode AI notes\n\n1. The speaker finds humor in Donald Trump's unconventional and sometimes rambling delivery, highlighting his comic timing and campy nature.\n\n2. A politician receives strong support from white evangelicals by tapping into an old American tradition of carnival, circus, and preacher-like charisma reminiscent of iconic figures like Billy Graham."
```

### Summary text types examples

These are the types of body:

#### no-body
```python
if len(hl_body) == 0:
```

[]

#### bullets
```python
elif hl_body[0].startswith('-'):
``` 
[
  '- Membership to our chat community is available on therestispolitics.com', 
  '- Listeners on Apple Podcast can easily subscribe for early access and ad free listening', 
  '- The hosts are Alistair Campbell and Rory Stewart', 
  '- Alistair Campbell is in Cape Cod, United States', 
  '- A tennis racket can be seen on the wall behind Alistair', 
  '- The tennis racket is old and has been used for a long time', 
  '- Alistair traveled on a tiny plane to reach his current location'
]

#### summary
```python    
elif "Summary:" in hl_body:
```

[
  'The central question is what mix of data sets should you use?', 
  'There are various considerations, such as different data sources, the importance of repetition (quality vs quantity), and the definition of good quality data. The belief that code or spending time on good sources like Wikipedia improves models lacks evidence.', 
  'Different data mixes yield varied results, with C4 dataset performing exceptionally well despite its problematic pre-processing.', 
  'Evaluating models for generation tasks is challenging, as there is uncertainty about what to measure.', 
  'Making reasonable choices based on evaluation becomes crucial.'
]

#### single-block
```python
elif len(hl_body) == 1:
```
[
  'The conversation highlights the roles and backgrounds of Pablo Alino and Matt Wysnisky, who are involved in Python community projects and work at Bloomberg. They discuss the use of profilers in Python, specifically C profile and profile from the standard library.'
]

#### multiline
```python
elif len(hl_body) > 1:
```

[
  'The podcast episode discusses several interconnected long-term trends that have profoundly shaped modern society, starting from the Industrial Revolution.', 
  
  '--The Industrial Revolution and its ripple effects:--', 
  
  '- The Industrial Revolution, beginning in the late 18th century, was fundamentally an energy revolution that transformed economies and work patterns. It led to a massive migration to cities, increased wealth, and advancements in medicine that drastically reduced child and maternal mortality. ',
  
  '- This, in turn, enabled women to enter the workforce, altering family structures, birth rates, and the overall nature of the economy. ', 
  
  "- Fewer children dying and women's increased participation in the workforce contributed to an aging population. This is a challenge because fewer working-age people support an increasing elderly population. ",
  
  '- The rise of the contraceptive pill further impacted fertility rates, giving women more control over family planning. ', 
  
  "- Automation of household tasks also played a part in women's increased participation in the labor market. ",
 
  '--Globalization and its consequences:--', 
  
  '- Globalization, particularly the free movement of capital and goods, led to a shift from a manufacturing-based to a service-based economy. ', 
  
  '- This made it more challenging for countries like the UK to compete internationally on manufacturing, forcing a focus on higher-skilled, service-based industries. ', 
  
  '- However, globalization also introduced increased vulnerability to global risks, such as pandemics and supply chain disruptions. ', 
  
  '- The increasing importance of education for success in the modern, service-based economy created a credentialist society and exacerbated social divisions. ', 
  
  '--The changing role of the state:--', 
  
  '- While globalization initially diminished the role of the state, recent events like the 2008 financial crisis and the COVID-19 pandemic have shown an increased reliance on state intervention and interventionism. ', 
  
  "- There's a growing expectation that the state should play a more active role in addressing social and economic challenges, yet there's simultaneous distrust in the competence of politicians."]

  
### Multiple locations example 

```bash
(Pdb) snipd_url
'https://share.snipd.com/episode/db7c3204-66c8-4d5d-a874-6892e67d82dd'
(Pdb) location
1853
(Pdb) hls
[HL(id:561404375), HL(id:798132634), HL(id:561404377), HL(id:798139309), HL(id:561404376), HL(id:798132659)]
(Pdb) for hl in hls:
...     print(hl.location, hl.highlighted_at)
...
1853 2023-07-10 09:07:25.266000
1853 2023-07-10 09:07:25.266000
1853 2023-07-10 09:07:43.488000
1853 2023-07-10 09:07:43.488000
1853 2023-07-10 09:07:52.170000
1853 2023-07-10 09:07:52.170000
(Pdb) y.snipd_hls_by_location_and_hl_at['https://share.snipd.com/episode/db7c3204-66c8-4d5d-a874-6892e67d82dd'][1853]
```


### Example Hl with same highlighted_at but clearly different Hls

```bash
(Pdb) hl1.highlighted_at, hl1.url
(datetime.datetime(2023, 9, 25, 12, 17, 59, 118000), 'https://share.snipd.com/snip/5706f5f3-19e6-4440-95cf-92a0fad2995e')
(Pdb) hl2.highlighted_at, hl2.url
(datetime.datetime(2023, 9, 25, 12, 17, 59, 118000), 'https://share.snipd.com/snip/6b55915b-0acc-49f6-8d9e-ef8abd6d7a54')


(Pdb) hl1.id, hl2.id
(600475461, 600475462)

(Pdb) hl1.location, hl2.location
(1590, 1614)

(Pdb) print(hl1.text)
Mussolini's March on Rome and Control of the Narrative

In 1922, Mussolini gained power through a strategic approach, allowing his supporters to march on Rome while he stayed behind. Despite Italy being a democracy with a king, many people in Britain are fascinated by Mussolini's rise to power. It's crucial to remember that people at that time were unaware of what would unfold. Although known for his violence, there were also those who admired the communists in the Soviet Union.

Transcript:
Dominic Sandbrook
So that's Mussolini. So 1922 is when Mussolini, he famously, he doesn't march on Rome. He lets his supporters march on Rome for him while he stays behind.

Tom Holland
But it had already been agreed, hadn't it? It had been agreed, exactly. So essentially, it's about showboating. It's about control of the narrative, all that kind of thing.

Dominic Sandbrook
I mean, Italy, of course, is another democracy. With a king. With a king. And there are lots of people in Britain who are Mussolini comes to power. So first of all, it's really important to emphasize with all of this. They don't know what we know. They don't know where the story will lead. And of course, Mussolini is violent. They know that Mussolini is violent. But I mean, there are loads of people who admire the communists in the Soviet Union,
(Pdb) print(hl2.text)
The Perception of Violence in Mussolini's Regime and the British Context

• It is important to acknowledge that people may not have the same knowledge or perspective as the speaker.

• The violence of Mussolini is known and acknowledged, but there are other violent groups admired by people as well.

• The stories of Mussolini's violence may shock people, but they may not view it as beyond human imagination.

• The presence of paramilitary organizations in Ireland and the ongoing war there demonstrate that political violence is not unfamiliar to the British way of life.

Transcript:
Dominic Sandbrook
First of all, it's really important to emphasize with all of this. They don't know what we know. They don't know where the story will lead. And of course, Mussolini is violent. They know that Mussolini is violent. But I mean, there are loads of people who admire the communists in the Soviet Union, and they're very violent. I mean, there are millions of people dying in the Russian Civil War. So when people, I think, read the stories about Mussolini's violence, about trade unionists being forced to drink castor oil or being beaten up or indeed killed, They may well think, Oh gosh, shocking. But I don't think they think this is barbarism beyond the scope of the human imagination.

Tom Holland
Also, there is a war going on in Ireland and there have been paramilitary organisations in Ulster and in the rest of Ireland that have made the running and have torn a chunk out of the United Kingdom. So it's not like the idea of political violence is something alien to the British way of life.

Dominic Sandbrook
No,
```