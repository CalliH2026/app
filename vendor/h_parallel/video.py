"""Local slide renderer, French speech synthesis, captions and H.264 MP4."""
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
FONT = str(ROOT/'static/h-kit/fonts/PlusJakartaSans.ttf')

def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)

def speech(text, output):
    if shutil.which('say'):
        aiff = output.with_suffix('.aiff')
        run(['say', '-v', 'Thomas', '-r', '155', '-o', str(aiff), text])
        run(['ffmpeg', '-y', '-i', str(aiff), '-ar', '24000', '-ac', '1', str(output)])
        aiff.unlink()
    elif shutil.which('espeak-ng'):
        run(['espeak-ng', '-v', 'fr', '-s', '155', '-w', str(output), text])
    else:
        raise RuntimeError('Installer une voix française : say (macOS) ou espeak-ng (Linux).')

def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','quiet','-show_entries','format=duration','-of','csv=p=0',str(path)]))

def stamp(seconds):
    ms = round(seconds*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

def render(dossier, folder):
    folder.mkdir(parents=True, exist_ok=True)
    font_path = FONT if Path(FONT).exists() else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    def font(n): return ImageFont.truetype(font_path,n)
    clips, captions, offset, number = [], [], 0., 1
    for i, scene in enumerate(dossier['scenes']):
        canvas=Image.new('RGB',(1280,720),'#f9f9fb'); draw=ImageDraw.Draw(canvas)
        draw.rectangle((0,0,1280,14), fill='#5a04bc')
        display_label=dossier.get('display_label','ALEX · 4e B')
        draw.text((74,55),'AVANT LE RENDEZ-VOUS   /   '+display_label,font=font(20),fill='#5a04bc')
        title=f'0{i+1}  /  {scene["title"]}'
        title_size=37
        while draw.textlength(title,font=font(title_size))>1120 and title_size>22: title_size-=1
        draw.text((74,125),title,font=font(title_size),fill='#1c1c26')
        def wrap_pixels(text,size):
            lines=[]; line=''
            for word in text.split():
                candidate=(line+' '+word).strip()
                if draw.textlength(candidate,font=font(size))>1120 and line:
                    lines.append(line); line=word
                else: line=candidate
            if line: lines.append(line)
            return lines
        body_size=33
        while len(wrap_pixels(scene['body'],body_size))*(body_size+15)>345 and body_size>24: body_size-=1
        y=225
        for line in wrap_pixels(scene['body'],body_size):
            draw.text((74,y),line,font=font(body_size),fill='#1c1c26'); y+=body_size+15
        draw.line((74,600,1206,600),fill='#d8d8e2',width=2)
        label='ÉVALUATION ET APPRÉCIATION DU PROFESSEUR' if 'teacher-assessment' in scene['source_ids'] else ('BARÈME ET COPIE · EXPLIQUENT LA NOTE' if i in (1,2) else ('QUESTION PARENTALE · VOCAL JOINT' if i==0 else ('RESSOURCE EXTERNE · POUR PROGRESSER' if any(s.startswith('web-') for s in scene['source_ids']) else 'FICHE MÉTHODE SCOLAIRE · POUR PROGRESSER')))
        draw.text((74,630),label,font=font(20),fill='#7a7a8a')
        draw.text((74,665),'Sources : '+', '.join(scene['source_ids']),font=font(15),fill='#687c70')
        img=folder/f'slide-{i}.png'; canvas.save(img)
        wav=folder/f'narration-{i}.wav'; speech(scene['narration'],wav)
        seconds=duration(wav)+.5
        clip=folder/f'scene-{i}.mp4'
        run(['ffmpeg','-y','-loop','1','-i',str(img),'-i',str(wav),'-t',str(seconds),'-vf','fps=24,format=yuv420p','-c:v','libx264','-preset','veryfast','-c:a','aac','-af','apad','-movflags','+faststart',str(clip)])
        clips.append(clip)
        chunks=textwrap.wrap(scene['narration'],width=95)
        for j,chunk in enumerate(chunks):
            start=offset+seconds*j/len(chunks); end=offset+seconds*(j+1)/len(chunks)
            captions.append(f'{number}\n{stamp(start)} --> {stamp(end)}\n{chunk}\n'); number+=1
        offset+=seconds
    listing=folder/'concat.txt'; listing.write_text(''.join(f"file '{p.name}'\n" for p in clips))
    srt=folder/'captions.srt'; srt.write_text('\n'.join(captions))
    mp4=folder/'capsule.mp4'
    run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(listing),'-i',str(srt),'-map','0:v','-map','0:a','-map','1:0','-c:v','copy','-c:a','copy','-c:s','mov_text','-metadata:s:s:0','language=fra','-movflags','+faststart',str(mp4)])
    # WebVTT also lets the local HTML player show the same subtitles.
    (folder/'captions.vtt').write_text('WEBVTT\n\n'+srt.read_text().replace(',','.'))
    (folder/'dossier.json').write_text(json.dumps(dossier,ensure_ascii=False,indent=2))
    return {'duration':round(offset),'video':f'/outputs/{folder.name}/capsule.mp4','captions':f'/outputs/{folder.name}/captions.vtt'}

if __name__=='__main__':
    fixture=json.loads((ROOT/'fixtures/alex.json').read_text())
    for item in fixture['audio'].values():
        output=ROOT/'fixtures'/item['file']
        if not output.exists(): speech(item['text'],output)
    print('Vocaux fictifs générés.')
