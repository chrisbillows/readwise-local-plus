# Ticket notes

Because writing all this shit in GitHub is dumb.

## Don't mess with cli.py args.all

There is a comment there but you will break `rwlp sync` and we're still using that locally from this WIP copy. (Because laziness).

## Current progress

- `cli.py` calls  `write_batch_to_obsidian` from `obsidian.py`.
- In testing I've been mainly using batch `113` and `112` (and previously `99`).

- So we are splitting highlights effectively it seems
- Working through formatting
    - HL Title is isolated and formatted
    - summary doesn't need formatting
- So issue is the quotes

Was considering nesting but not sure it's better.
Going with this is as the desired format:

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

- Now we have split transcripts into speaker / text


## Reference

TRANSCRIPT SAMPLES:

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