"""Generate code-native app icons from the RamPilot chip mark."""
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1]
image=Image.new('RGBA',(1024,1024),(0,0,0,0));draw=ImageDraw.Draw(image)
draw.rounded_rectangle((32,32,992,992),radius=220,fill='#10151e')
draw.rounded_rectangle((238,278,786,746),radius=55,outline='#5ce0b8',width=38)
for x in [310,445,580,715]:
 draw.line((x,205,x,270),fill='#5ce0b8',width=32)
 draw.line((x,754,x,819),fill='#5ce0b8',width=32)
for x in [330,465,600]:draw.rounded_rectangle((x,378,x+90,646),radius=22,fill='#5ce0b8')
image.save(root/'RamPilot.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
image.save(root/'mac/RamPilot.icns')
image.resize((256,256),Image.Resampling.LANCZOS).save(root/'assets/logo.png')
