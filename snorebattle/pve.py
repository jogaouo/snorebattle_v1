"""正式單人對戰：固定中等模型、玩家成就、本機事件紀錄與回放。"""
from copy import deepcopy
from .achievements import Achievements
from .ai.controller import ComputerController
from .ai.environment import observe,stable_seed
from .ai.policy import Policy,load_profile
from .core import Game,Command
from .lab_modes import install_game
from .replay import Recorder


class PlayerAchievements(Achievements):
    def __init__(self,path,human_role):
        super().__init__(path);self.human_role=human_role

    def consume(self,event):
        if event['type']=='game_ended' or event.get('player')==self.human_role:
            super().consume(event)


class PvEMode(ComputerController):
    kind='pve'
    def __init__(self,app,human_role):
        if human_role not in (0,1):raise ValueError('請選擇有效角色')
        name='loose_1' if human_role==0 else 'tight_0'
        self.profile_path=app.root/'data/ai'/f'{name}.json'
        self.profile=load_profile(self.profile_path)
        if self.profile['role']!=1-human_role:raise ValueError('電腦模型的角色不正確')
        game=Game(deepcopy(app.config),deepcopy(app.catalog),app.root/'saves')
        game.achievements=PlayerAchievements(app.root/'saves/achievements.json',human_role)
        agent=Policy(self.profile,stable_seed(game.seed,1-human_role))
        super().__init__(app,human_role,agent,observe)
        self.recorder=Recorder(game,dict(mode='pve',difficulty='medium',human_role=human_role,
                                       profile=deepcopy(self.profile)))
        self.saved=False
        install_game(app,game)

    def after_command(self,player,action,uid):
        self.recorder.append(self.app.game,Command(player,action,uid))
        self.recorder.data['commands'][-1]['decision']=self.agent.last_reason if player!=self.human_role else '玩家操作'
        super().after_command(player,action,uid)
        if self.app.game.phase=='ended':self.save()

    def save(self):
        if self.saved:return
        game=self.app.game
        scores=[p.score for p in game.players]
        winner=None if scores[0]==scores[1] else int(scores[1]>scores[0])
        self.recorder.data['metadata']['result']=dict(scores=scores,winner=winner if game.phase=='ended' else None,
            human_role=self.human_role,ai=self.profile['name'],
            snorer='玩家' if self.human_role==0 else self.profile['name'],
            slapper='玩家' if self.human_role==1 else self.profile['name'],reason='ended' if game.phase=='ended' else 'interrupted')
        try:self.recorder.save(self.app.root/'saves/replays'/f'{game.id}.json',game)
        except OSError as error:
            self.app.notify('對局回放儲存失敗：'+str(error));return
        self.saved=True

    def banner(self):
        roles=('打呼者','打巴掌者')
        self.app.text(f'單人模式 · 中等｜你：{roles[self.human_role]}｜電腦：{roles[1-self.human_role]}',42,95,14,(151,169,194))


def start_pve(app,human_role):
    mode=PvEMode(app,human_role)
    app.lab_mode=mode;app.camera_duration=650
