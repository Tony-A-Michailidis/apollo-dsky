# Setting up a screenshot

How to get the DSKY panel into a good-looking state for a screenshot: engine burning, live
descent numbers, and the Apollo 11 program alarm lit.

## Start the simulator

In a WSL terminal:

```bash
source ~/venvs/apollo-dsky/bin/activate
cd <your folder>/apollo-dsky
dsky
```

Leave that terminal open and open http://127.0.0.1:8000/ in your Windows browser.

## The scene

Click the keys on the panel, or type: `V` for VERB, `N` for NOUN, `Enter` for ENTR, `P` for PRO,
`R` for RSET, `K` for KEY REL.

1. Click **8x** in the side panel so the sim runs eight times faster than real time.
2. Key `V37E63E` to select P63, the braking phase. When V06N61 flashes, press `P`.
3. About eight seconds later the display blanks for a moment, then V99N62 flashes and asks
   to enable the engine. Press `P`. The engine lights at 10 % and throttles up.
4. Key `V16N68E`. The three rows now show slant range, time to go and the landing radar
   delta-H, the display Aldrin watched during the descent. Radar delta-H stays blank until the
   landing radar locks below 40,000 ft.
5. For the alarm, click **AUTO TRACK** under the rendezvous radar switch. About four seconds
   later at 8x, the yellow PROG lamp lights with a 1202 or 1201 alarm, as on Apollo 11.
   Key `V05N09E` to show the alarm codes in the registers.
6. Click **pause** to freeze the panel while you take the shot.

## Take the screenshot

Press `Windows+Shift+S` and drag a box around the panel. The image goes to the clipboard, and
the Snipping Tool notification lets you save it as a file.

Press `Ctrl+C` in the WSL terminal when you are done to stop the server.

## Other scenes

| Scene | How |
|---|---|
| Every segment and lamp lit | Key `V35E`, the lamp test. It lasts about five seconds. |
| Mission clock running | Key `V16N36E`. |
| Approach phase | Let the landing run from step 3 until P64 appears at about 7,500 ft. N64 shows time to go, the landing point angle, altitude rate and altitude. |
| After touchdown | Let it land by itself. P68 flashes V06N43 with latitude, longitude and altitude. |
| Start over | Click **reset** in the side panel. |
