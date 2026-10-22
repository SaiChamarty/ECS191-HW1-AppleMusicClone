## User testing (5 people)

### Each user and their feedback / interview experience
1. Achintya (Guy with the cap):
  - What does it do?
    - Search for a song and get recommended songs based on genre.
  - Where they got stuck?
    - They easily performed the given task without much hesitation. I observed some confusion on what clicking on each song does,
      so they clicked on the three dots on the side to find the similar song. And they could not test if they sounded similar or
      not because the main song that was the comparison was not added to the playlist...
  - Their answers to the debrief questions
    - Difficulty 1 (very easy)
    - The one thing they wanted to change was add more features to the app like radio or podcasts similar to Apple Music.
    - He described this app as something that users could use to find a favorite song and add it to playlist. It was not
      super accurate to what I was hoping, but that means I could improve in somehow displaying a text on the homepage
      something like: "find similar music to a song".
      
2. Yatin (Outdoor interview)
  - What does it do?
    - Find songs in the similar tempo or genre
  - Where they got stuck?
    - They expected the song to start playing when clicked. So they used the three buttons instead of directly clicking on
      the song to initiate similarity checker. But they did not struggle in performing the task. They seem to question the
      point of doing all of this but at the end they found the app very useful. They seemed to not trust the output of the
      app completely - 50/50. They expected the playlist making even more faster. 
  - Their answers to the debrief questions
    - Difficulty 2-3 (Mid). Issue was that he had to go through each one of songs to make sure they are similar and that
      too once the playlist was created.
    - Analyze the songs more deeper as the outputs do not seem great - only 50% accuracy. 
    - He described the app to be helpful in making a playlist of similar songs.

3. Gavin (The green outdoors)
  - What does it do?
    - Put a song you like and it finds similar artists and songs.
  - Where they got stuck?
    - Gavin thought he had to listen to each of the songs himself and find similar songs in the app himself. I am not sure
      whether the app was not clear enough or whether I did not explain properly, but that was something he struggled with.
      Once I told him the app does it for him (I think I helped him too early), he did not struggle to create the playlist
      with similar songs. He did get confused in finding the add to playlist button, but eventually found it. He also told
      some of the songs are pretty similar. 60% of them are similar. 
  - Their answers to the debrief questions
    - Difficulty 1 (Easy).
    - Similar songs in the same genre. More specificity based on genre. 
    - One sentence description: Find similar songs.

4. Allen (2 doors behind him)
  - What does it do?
    - You know a song, find other songs you might like. It shows similar songs to the one you like. 
  - Where they got stuck?
    - They did not stuck anywhere. It was very easy for them to find similar songs and add to a playlist. They did struggle
      to understand how exactly to play a song. They clicked on the song bar and it asked to find 10 more songs again.
      It was the little play button they should've to click on, which they eventually figured. So That might be an interesting
      feature fix. To compare the songs, they did not have access to the original song. So maybe when creating the playlist, it
      also adds the searched song. Song search could be better. Needs more specificity. 
  - Their answers to the debrief questions
    - Difficulty - 1 (Very easy to find similar songs). Did not find songs that were super similar. 
    - Optimizing it to find songs that are even more similar.
    - Description provided: This is an app that helps you find songs that sound similar to a song you like.

5. Sanat (Indoors, black jacket)
  - What does it do?
    - Its an app to find more songs like a specific artist or a particular song. Maybe upload playlists from Spotify.
  - Where they got stuck?
    - He wanted to listen to the songs and wanted to only add the ones he liked to a playlist. But there was a button to add
      all 10 to the playlist and he did that instead. It was easy for them to find similar songs and show me the playlist.
      Output might me mixed. Showed weird English matches for a traditional Indian song. 
  - Their answers to the debrief questions
    - Difficulty 1 (Very Easy to make a playlist). 
    - Magic wand change: Add a dark mode as he likes dark mode.
    - App Description provided: Music Finder
   
### Patterns Observed in Users
I observed all of them easily navigating the app and making a playlist with similar songs to a song they selected.  
I also observed them mentioning similar artists during their 5 second skim, but my app does not have that functionality.  
I think the home page description is a little misleading there.  

All 5 of them were not satisfied with the results of the similarity search. I used 30 seconds snippets to compare songs, 
but more depth is required to capture the similarity. I think training an ML model from scratch on this task itself is 
the best way to get deeper similarities.  

Multiple people got confused with clicking the song's bar as a whole vs clicking on the play button. The play button is what
plays the song snippets while clicking on the song bar as a whole will trigger a sheet pop up to find similar songs. All of them
used the add all 10 to the playlist button, but when they add one button at a time, the back functionality does not exist to go 
back to the same list of similar songs. So they have to click on find 10 similar songs again and again if they want to add multiple 
songs to a playlist. So there should be a way to select multiple songs at once in the sheet pop up itself to make this easier.

I also observed that no one payed attention to the match percentages when they search the song. The match percentages should be 
largest and bolder to be more visible.

### What I would change in the app based on what I learned?
I would make the following changes to the app based on the interviews:
- Make the similarity search more specific and deeper by getting the backend to analyze the whole song, genre, artist specificity,
  as well as the beats, tempo etc.
- Make the AI vibe tag, sound match % bolder and larger font in the song search sheet so that it won't be ignored.
- Add a selector functionality to add multiple songs at once instead of adding only one or all 10 at once.
- Implement backward and forward buttons to preserve the search already done when adding to playlist. This way users will not
  have to click on the similarity button again and again.
- Add a dark more as well so that it satisfies users who like dark screens.

Overall, interviews honestly helped me understand a lot on what the users actually need vs what I built. 
2 out of 5 want me to provide them access to this app so that they can play around with it even more!!


