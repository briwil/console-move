import math, re
from PIL import Image, ImageDraw, ImageFont
src = open(__import__("os").path.join(__import__("os").path.dirname(__file__), "move_test.py")).read()
ns = {}; exec(src[src.index("FONT = {"):src.index("def render")], ns); F = dict(ns["FONT"])
F.update({".": (0,0x60,0x60,0,0), "/": (0x20,0x10,0x08,0x04,0x02), ">": (0x41,0x22,0x14,0x08,0), "+": (0x08,0x08,0x3E,0x08,0x08)})
S = {  # 3x5 mini font, rows top->bottom, 3 bits each
 "0":"777575757", }
MINI = {"0":["111","101","101","101","111"],"1":["010","110","010","010","111"],"2":["111","001","111","100","111"],
 "3":["111","001","111","001","111"],"4":["101","101","111","001","001"],"5":["111","100","111","001","111"],
 "6":["111","100","111","101","111"],"7":["111","001","010","010","010"],"8":["111","101","111","101","111"],"9":["111","101","111","001","111"],
 " ":["000"]*5,"C":["111","100","100","100","111"],"L":["100","100","100","100","111"],"R":["110","101","110","101","101"],
 "V":["101","101","101","101","010"],"O":["111","101","101","101","111"],"P":["111","101","111","100","100"],"A":["010","101","111","101","101"],
 "N":["101","111","111","111","101"],"T":["111","010","010","010","010"],"K":["101","101","110","101","101"],"S":["111","100","111","001","111"],
 "E":["111","100","111","100","111"],"M":["101","111","111","101","101"],"B":["110","101","110","101","110"],"/":["001","001","010","100","100"],".":["000","000","000","000","010"],
 "I":["111","010","010","010","111"],"D":["110","101","101","101","110"],"G":["111","100","101","101","111"],"H":["101","101","111","101","101"]}
class Scr:
    def __init__(s): s.p = [[0]*128 for _ in range(64)]
    def px(s,x,y,v=1):
        if 0<=x<128 and 0<=y<64: s.p[y][x]=v
    def rect(s,x,y,w,h,v=1):
        for yy in range(y,y+h):
            for xx in range(x,x+w): s.px(xx,yy,v)
    def frame(s,x,y,w,h,v=1):
        s.rect(x,y,w,1,v); s.rect(x,y+h-1,w,1,v); s.rect(x,y,1,h,v); s.rect(x+w-1,y,1,h,v)
    def text(s,x,y,t,v=1):
        for k,ch in enumerate(t):
            for c,b in enumerate(F.get(ch,F[" "])):
                for r in range(7):
                    if b>>r&1: s.px(x+k*6+c,y+r,v)
        return len(t)*6-1
    def mini(s,x,y,t,v=1):
        for k,ch in enumerate(t):
            for r,row in enumerate(MINI.get(ch,MINI[" "])):
                for c,b in enumerate(row):
                    if b=="1": s.px(x+k*4+c,y+r,v)
        return len(t)*4-1
    def lines(s,cx,cy,frac,n,pitch,tall,short=1,fall=1.6):
        peak=frac*(n-1); x0=cx-((n-1)*pitch)//2
        for k in range(n):
            h=max(short,round(tall*math.exp(-abs(k-peak)/fall)))
            s.rect(x0+k*pitch,cy-h//2,1,max(1,h))
    def img(s,scale=5):
        im=Image.new("RGB",(128*scale,64*scale),(10,10,10)); d=ImageDraw.Draw(im)
        for y in range(64):
            for x in range(128):
                if s.p[y][x]: d.rectangle((x*scale,y*scale,x*scale+scale-2,y*scale+scale-2),fill=(235,235,235))
        return im

# A: recorder
a=Scr()
a.rect(0,0,128,9); a.text(1,1,"PLAY",0); a.text(36,1,"120 BPM",0); a.text(92,1,"03.2",0)
clips={1:[(8,40),(60,90)],2:[(8,120)],3:[(20,50),(70,110)],4:[(8,30)],5:[],6:[(40,127)],7:[(8,60)],8:[(90,127)]}
for t in range(1,9):
    y=11+(t-1)*5+(t>4)*0
    if t==3:
        a.rect(0,y-1,7,7); a.mini(2,y,str(t),0)
    else: a.mini(2,y,str(t))
    for x0,x1 in clips[t]: a.rect(x0+2,y+1,x1-x0,3)
    a.rect(10,y+2,118,1) if not clips[t] else None
for y in range(10,54,2): a.px(66,y)
a.rect(0,54,128,1); a.text(1,57,"T3 VOL 80 PAN C")
# B: drum list
b=Scr()
b.rect(0,0,128,9); b.text(1,1,"KICK",0); b.text(40,1,"OSC+AMP",0); b.mini(113,2,"1/4",0)
names=["TUNE","FINE","WAVE","PULSE W","ATTACK","DECAY","SLOPE",""]; vals=[0.5,0.45,0.2,0.7,0.05,0.6,0.35,0]
for i,(n,v) in enumerate(zip(names,vals)):
    col,row=divmod(i,4); x=col*64; y=12+row*12
    if not n: continue
    b.mini(x+1,y+1,str(i+1)); b.text(x+6,y,n[:7])
    b.lines(x+56,y+3,v,5,2,7,1,1.0)
b.rect(63,11,1,47)
for k in range(4): (b.rect if k==0 else b.frame)(50+k*8,59,5,4)
# C: turning
c=Scr()
c.rect(0,0,128,9); c.text(1,1,"KICK",0); c.text(40,1,"OSC+AMP",0); c.mini(113,2,"1/4",0)
c.lines(64,32,0.62,29,4,30,1,2.2)
w=len("DECAY")*6; c.text(2,55,"6 DECAY"); c.text(127-4*6,55,"63.0")
ims=[x.img() for x in (a,b,c)]
W=ims[0].width; H=ims[0].height
out=Image.new("RGB",(W,3*H+3*30+20),(255,255,255)); d=ImageDraw.Draw(out)
try: fnt=ImageFont.truetype("../hardware/keycaps/fonts/Lato-ExtraBold.ttf",15)
except: fnt=None
caps=["A. Recorder: 8 tracks as thin tape strips, playhead dotted, selected track inverted",
      "B. Drum page at rest: the page's settings listed in knob order (1-4 left, 5-8 right)",
      "C. Drum page while turning knob 6: that one setting fills the screen with its bars"]
y=5
for im,cap in zip(ims,caps):
    d.text((4,y),cap,fill=(0,0,0),font=fnt); y+=28; out.paste(im,(0,y)); y+=H+5
out.save("move-screens.png")
