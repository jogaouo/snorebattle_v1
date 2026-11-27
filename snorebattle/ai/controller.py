"""正式PvE與開發測試共用的電腦回合控制，不接觸玩家的操作。"""
import pygame


class ComputerController:
    def __init__(self,app,human_role,agent,observe):
        self.app=app;self.human_role=int(human_role)
        self.agent=agent;self.observe=observe
        self.applying=False;self.next_action=0;self.message=''

    def is_bot_turn(self):
        return self.app.game.active!=self.human_role and self.app.game.phase!='ended'

    def after_command(self,*args):
        self.next_action=pygame.time.get_ticks()+450

    def tick(self):
        app=self.app
        if not self.is_bot_turn() or app.camera_moving() or app.log_open or pygame.time.get_ticks()<self.next_action:return
        try:
            observation=self.observe(app.game)
            action,uid=self.agent.choose(observation)
            if (action,uid) not in observation['legal']:raise ValueError('電腦回傳非法操作')
            app.selected=uid;self.applying=True
            app.command(action)
        except Exception as error:
            self.message=str(error);app.notify('電腦已停止：'+str(error))
            self.next_action=10**15
        finally:
            self.applying=False;app.selected=None;app.inspect_tool=False
