"""python main.py；本機 .vendor 優先，也支援一般 pip 安裝。"""
from pathlib import Path
import argparse
import os
import sys

ROOT=Path(__file__).resolve().parent
if sys.platform=='win32' and sys.version_info[:2]==(3,12):
    sys.path.insert(0,str(ROOT/'.vendor'))
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke',type=int,default=None,help='無視窗驗證指定幀數')
    parser.add_argument('--screenshot')
    parser.add_argument('--battle',action='store_true')
    args=parser.parse_args()
    if args.smoke:
        os.environ['SDL_VIDEODRIVER']='dummy'
        os.environ['SDL_AUDIODRIVER']='dummy'
    try:
        from snorebattle.app import App
    except ModuleNotFoundError as error:
        if error.name=='pygame':
            print('缺少 pygame，請先執行：python -m pip install -r requirements.txt')
            return 1
        raise
    app=App(ROOT)
    if args.battle: app.start_game()
    app.run(args.smoke,args.screenshot)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
