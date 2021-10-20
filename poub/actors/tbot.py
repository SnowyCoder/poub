import logging
import re
from enum import Enum

import telegram
from pykka import ActorProxy, ThreadingActor
from telegram import Update
from telegram.ext import Updater, CallbackContext, ConversationHandler, Dispatcher, CommandHandler, MessageHandler, \
    Filters, DispatcherHandlerStop

from actorutil.event import EventListener
from timetable import normalize_teacher_name
from .browser import BookResult, BookResultType, BookTurnResultType
from .userdb import User
from config import config

USER_WHITELIST = [int(x) for x in config['TELEGRAM_WHITELIST'].split(' ')]
USER_WHITELIST_FILTER = Filters.user(USER_WHITELIST)
TOKEN = config['TELEGRAM_TOKEN']

USERNAME_PATTERN = re.compile(r'^\d+$')
PASSWORD_PATTERN = re.compile(r'^[^\s]+$')


class AddSubjectConversation(Enum):
    FIND_TEACHER = 1
    FIND_SUBJECT = 2


class RemoveSubjectConversation(Enum):
    FIND_SUBJECT = 1


class LoginConversation(Enum):
    SEND_USERNAME = 1
    SEND_PASSWORD = 2


class TelegramBotActor(EventListener, ThreadingActor):
    def __init__(self, dt_ref: ActorProxy, userdb_ref: ActorProxy, booker_ref: ActorProxy):
        super().__init__()
        self.dt_ref = dt_ref
        self.userdb_ref = userdb_ref
        self.booker_ref = booker_ref

        self.event_subscribe(self.actor_ref, booker_ref.proxy().events, 'booked', self._on_booked)
        self.updater = Updater(token=TOKEN)
        self.bot = self.updater.bot  # type: telegram.Bot

        self._init()

    def _pre_check(self, update: Update, ctx: CallbackContext) -> None:
        if update.effective_user.id not in USER_WHITELIST:
            raise DispatcherHandlerStop()

        ctx.user_data['user'] = self.userdb_ref.proxy().create_user(update.effective_user.id).get()

    def _cmd_help(self, update: Update, ctx: CallbackContext) -> None:
        message = ('Welcome to the UniMoRe booker!:\n' +
                   '/login perform the login\n' +
                   '/logout logout from unimore!\n' +
                   '/add add a subject to follow\n' +
                   '/list list all the followed subjects\n' +
                   '/remove remove a subject from the followed\n'
                   '/help I\'ll explain recursion to you!')
        update.effective_chat.send_message(message)

    def _on_booked(self, user: User, res: BookResult):
        """Called when the BookActor has finished booking a user"""
        for index, turn in enumerate(res.booked):
            if turn.res == BookTurnResultType.OK:
                self.bot.send_document(
                    user.tid,
                    document=turn.pdf,
                    filename=f'presenza{index + 1}.pdf',
                    caption=f'{turn.info.room} {turn.info.trange}'
                )
            else:
                self.bot.send_message(
                    user.tid,
                    f'{turn.info.room} {turn.info.trange} Already booked'
                )


        err_name = ({
            BookResultType.OK: 'ok',
            BookResultType.LOGIN_FAILED: 'Login failed',
            BookResultType.TIMEOUT: 'Timeout',
            BookResultType.UNKNOWN_ERR: 'Unknown'
        }).get(res.type, '???')
        if err_name != 'ok':
            message = ('Error while booking: ' + err_name + '\n Failed to book:\n' +
                       '\n'.join(f'- {i.room} {i.trange} {i.book_link}' for i in res.remaining))
            self.bot.send_message(user.tid, message)

    def _cmd_login(self, update: Update, ctx: CallbackContext):
        update.message.chat.send_message('WARNING: the username and password will be STORED in the daemon pc ' +
                                         'please be sure to trust the host before you continue!\n' +
                                         'Type /cancel to turn back\n' +
                                         'Send the username:')
        return LoginConversation.SEND_USERNAME

    def _on_login_username(self, update: Update, ctx: CallbackContext):
        uname = update.message.text
        if USERNAME_PATTERN.fullmatch(uname) is None:
            update.effective_chat.send_message('Invalid username')
            return
        update.effective_chat.send_message('Great, now send the password')
        ctx.user_data['username'] = uname
        return LoginConversation.SEND_PASSWORD

    def _on_login_password(self, update: Update, ctx: CallbackContext):
        username = ctx.user_data['username']
        password = update.message.text
        update.message.delete()
        if PASSWORD_PATTERN.fullmatch(password) is None:
            update.effective_chat.send_message('Invalid password')
        ctx.user_data.pop('username')
        self.userdb_ref.proxy().user_login(update.message.from_user.id, username, password).get()
        # TODO: check login
        update.effective_chat.send_message('Login succesfull!')
        return ConversationHandler.END

    def _cmd_logout(self, update: Update, ctx: CallbackContext):
        self.userdb_ref.proxy().login(update.message.from_user.id, None, None).get()
        update.effective_chat.send_message('Logout succesfull!')

    def _cmd_add(self, update: Update, ctx: CallbackContext):
        update.message.chat.send_message('Hello!\nText me the professor name please')
        return AddSubjectConversation.FIND_TEACHER

    def _on_teacher_name(self, update: Update, ctx: CallbackContext):
        name = normalize_teacher_name(update.message.text)
        try:
            subjs = self.dt_ref.proxy().get_teacher_subjects(name).get()  # type: set[str]
        except:
            logging.exception("Cannot find teacher")
            update.message.chat.send_message(f"Cannot find teacher {name}")
            return
        ctx.user_data['teacher'] = name
        ctx.user_data['subjects'] = subjs

        update.message.chat.send_message('What subject do you want to follow?\n' +
                                         '\n'.join('-' + subject for subject in subjs))
        return AddSubjectConversation.FIND_SUBJECT

    def _on_teacher_subject(self, update: Update, ctx: CallbackContext):
        teacher = ctx.user_data['teacher']  # type: str
        subjects = ctx.user_data['subjects']  # type: set[str]
        subjtext = update.message.text.lower()

        selected = [x for x in subjects if subjtext in x.lower()]

        if len(selected) == 0:
            update.message.chat.send_message(f'Wut? I don\'t know {update.message.text}')
            return
        if len(selected) > 1:
            update.message.chat.send_message(f'Mmmh, {update.message.text} is ambiguos!')
            return

        self.userdb_ref.proxy().user_add_subject(update.effective_user.id, (teacher, selected[0]))
        update.message.chat.send_message('Ok, subject added!')
        return ConversationHandler.END

    def _on_cancel(self, update: Update, ctx: CallbackContext):
        update.message.chat.send_message('Cancelled!')
        ctx.user_data.clear()

    def _on_timeout(self, _update: Update, ctx: CallbackContext):
        ctx.user_data.clear()

    def _cmd_list(self, update: Update, ctx: CallbackContext):
        user = ctx.user_data['user']  # type: User
        message = (f'You have {len(user.subjects)} subjects:\n' +
                   '\n'.join(f'-{x[0]} - {x[1]}' for x in user.subjects))
        update.effective_chat.send_message(message)

    def _cmd_remove(self, update: Update, ctx: CallbackContext):
        user = ctx.user_data['user']  # type: User
        if len(user.subjects) <= 0:
            update.effective_chat.send_message('You are not subscribed to any subject')
            return ConversationHandler.END

        update.effective_chat.send_message('Of course! What subject do you want to unsusbscribe from?')
        return RemoveSubjectConversation.FIND_SUBJECT

    def _on_remove_subject(self, update: Update, ctx: CallbackContext):
        user = ctx.user_data['user']  # type: User
        subject = update.message.text.lower()
        selected = [x for x in user.subjects if subject in x[1].lower()]

        if len(selected) == 0:
            update.effective_chat.send_message('Cannot find subject')
            return
        elif len(selected) > 1:
            update.effective_chat.send_message(
                'There are multiple subjects with that name:\n' +
                '\n'.join(f'{x[0]} - {x[1]}' for x in selected)
            )
            return
        self.userdb_ref.proxy().user_remove_subject(update.message.from_user.id, selected[0]).get()
        update.effective_chat.send_message('Subject removed!')

        return ConversationHandler.END

    def _init(self):
        d = self.updater.dispatcher  # type: Dispatcher
        d.add_handler(MessageHandler(Filters.all, self._pre_check), group=-1),
        d.add_handler(CommandHandler('help', self._cmd_help))
        d.add_handler(ConversationHandler(
            entry_points=[
                CommandHandler('login', self._cmd_login)
            ],
            states={
                LoginConversation.SEND_USERNAME: [MessageHandler(Filters.text, self._on_login_username)],
                LoginConversation.SEND_PASSWORD: [MessageHandler(Filters.text, self._on_login_password)],
            },
            fallbacks=[CommandHandler('cancel', self._on_cancel)],
        ))
        d.add_handler(CommandHandler('logout', self._cmd_logout))
        d.add_handler(ConversationHandler(
            entry_points=[CommandHandler('add', self._cmd_add)],
            states={
                AddSubjectConversation.FIND_TEACHER: [MessageHandler(Filters.text, self._on_teacher_name)],
                AddSubjectConversation.FIND_SUBJECT: [MessageHandler(Filters.text, self._on_teacher_subject)],
                ConversationHandler.TIMEOUT: [MessageHandler(Filters.all, self._on_timeout)],
            },
            fallbacks=[CommandHandler('cancel', self._on_cancel)],
        ))
        d.add_handler(ConversationHandler(
            entry_points=[CommandHandler('remove', self._cmd_remove)],
            states={
                RemoveSubjectConversation.FIND_SUBJECT: [MessageHandler(Filters.text, self._on_remove_subject)],
                ConversationHandler.TIMEOUT: [MessageHandler(Filters.all, self._on_timeout)],
            },
            fallbacks=[CommandHandler('cancel', self._on_cancel)],
        ))
        d.add_handler(CommandHandler('list', self._cmd_list))

    def on_start(self) -> None:
        self.updater.start_polling()

    def on_stop(self) -> None:
        self.updater.stop()
        self.updater.is_idle = False


