# Proposal: Apple Music Clone

## 1. The app
- I would like to clone Apple Music. The reason for this is I really like the app and use it every single day. Without it and its music, a single day doesn't go by for me. In addition to that, I really like its User Interface. 

## 2. The fundamental problem
- Apple Music enables people to listen to a wide variety of music by having any song you want to listen available instantly without buying record albums or owning physical media.

## 3. What I'll keep
- The way Apple Music lists tracks in its playlists are clean, simple and with an image. A good UI is always something to keep!
- I will keep the Library and Song lookup, as those are the two functionalities I mostly use, and aid the core functionality of seed search. 

## 4. What I'll change or remove
- One main loop I would like to implement is seed search: "more like {song_X}" in the search bar and it automatically shows songs similar to the seed song. Apple Music does this using "Create Station", but I observed when I played a Soul Tamil Song, it suggested more Tamil songs with similar artists rather than match for vibe and similar genres. For this matching, I'll start with LLM-based similarity and evaluate whether results match the feel, moving to audio-based ML models if they don't.
- I will remove the Home, Radio and New tabs and only keep Library and the Lookup input box as they aid in the core functionality of seed search and saving looked-up music.
- Within Library there will be playlists added by the user using lookup and "add to playlist" functionality.
