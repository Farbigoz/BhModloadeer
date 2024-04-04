import os
import sys
import time
import py7zr
import urllib
import rarfile
import zipfile
import traceback
import threading
import webbrowser
import subprocess
import multiprocessing
import webbrowser

# (https://stackoverflow.com/questions/9144724/unknown-encoding-idna-in-python-requests)
import encodings.idna

from typing import List

try:
    import core
    from core import NotificationType, Notification, Environment, CORE_VERSION

    import core.core.ffdec

    JAVA_FOUND = True
except ImportError as e:
    NotificationType = Notification = Environment = CORE_VERSION = None

    if e.msg == "Java not found!":
        JAVA_FOUND = False
    else:
        sys.excepthook(*sys.exc_info())

from PySide6.QtCore import QSize, QTranslator, QLocale, QTimer, Signal
from PySide6.QtGui import QIcon, QFontDatabase
from PySide6.QtWidgets import QMainWindow, QApplication

from ui.ui_handler.window import Window
from ui.ui_handler.header import HeaderFrame
from ui.ui_handler.loading import Loading
from ui.ui_handler.mods import Mods
from ui.ui_handler.progressdialog import ProgressDialog
from ui.ui_handler.buttonsdialog import ButtonsDialog
from ui.ui_handler.acceptdialog import AcceptDialog

from ui.utils.layout import ClearFrame, AddToFrame
from ui.utils.version import GetLatest, GITHUB, REPO, VERSION, GIT_VERSION, PRERELEASE, GAMEBANANA
from ui.utils.textformater import TextFormatter
from ui.utils.mainthread import QExecMainThread

import ui.ui_sources.translate as translate


SUPPORT_URL = "https://www.patreon.com/bhmodloader"

PROGRAM_NAME = "Brawlhalla ModLoader"


def InitWindowSetText(text):
    if getattr(sys, "frozen", False):
        try:
            import pyi_splash
            pyi_splash.update_text(text)
        except:
            pass


def InitWindowClose():
    if getattr(sys, "frozen", False):
        try:
            import pyi_splash
            pyi_splash.update_text("application")
            pyi_splash.close()
        except:
            pass


def TerminateApp(exitId=0):
    for proc in multiprocessing.active_children():
        proc.kill()
    os.kill(multiprocessing.current_process().pid, exitId)
    sys.exit(exitId)


class ImportQueue:
    def __init__(self):
        self.urlQueue = []
        self.signalUrl = None
        self._readUrlQueue = False

        self.fileQueue = []
        self.signalFile = None
        self._readFileQueue = False

    def setUrlSignal(self, signalUrl):
        self.signalUrl = signalUrl

    def _emitUrl(self):
        while True:
            try:
                if self.signalUrl is None:
                    time.sleep(0.1)
                else:
                    self.signalUrl.emit()
                    break
            except:
                time.sleep(0.1)

    def addUrl(self, url):
        self.urlQueue.append(url)

        if not self._readUrlQueue:
            threading.Thread(target=self._emitUrl).start()

    def iterUrl(self):
        self._readUrlQueue = True

        while self.urlQueue:
            yield self.urlQueue.pop(0)

        self._readUrlQueue = False

    def setFileSignal(self, signalFile):
        self.signalFile = signalFile

    def _emitFile(self):
        while True:
            try:
                if self.signalFile is None:
                    time.sleep(0.1)
                else:
                    self.signalFile.emit()
                    break
            except:
                time.sleep(0.1)

    def addFile(self, file):
        self.fileQueue.append(file)

        if not self._readFileQueue:
            threading.Thread(target=self._emitFile).start()

    def iterFile(self):
        self._readFileQueue = True

        while self.fileQueue:
            yield self.fileQueue.pop(0)

        self._readFileQueue = False


class ModLoader(QMainWindow):
    importQueue = ImportQueue()

    modsPath = os.path.join(os.getcwd(), "Mods")

    errors: List[Notification] = []

    app = None

    def __init__(self):
        super().__init__()
        self.ui = Window()
        self.ui.setupUi(self)

        QExecMainThread.init(self)

        InitWindowSetText("ui")

        self.setWindowTitle(PROGRAM_NAME)
        self.setWindowIcon(QIcon(':/icons/resources/icons/App.ico'))

        self.loading = Loading()
        self.header = HeaderFrame(githubMethod=lambda: webbrowser.open(f"{GITHUB}/{REPO}"),
                                  supportMethod=lambda: webbrowser.open(SUPPORT_URL),
                                  infoMethod=self.showInformation)
        self.mods = Mods(installMethod=self.installMod,
                         uninstallMethod=self.uninstallMod,
                         reinstallMethod=self.reinstallMod,
                         deleteMethod=self.deleteMod,
                         reloadMethod=self.reloadMods,
                         openFolderMethod=self.openModsFolder)
        self.progressDialog = ProgressDialog(self)
        self.buttonsDialog = ButtonsDialog(self)
        self.acceptDialog = AcceptDialog(self)

        self.setLoadingScreen()

        # self.resize(QSize(977, 550))
        self.setMinimumSize(QSize(850, 550))

        threading.Thread(target=self.checkNewVersion).start()

        self.queueUrlSignal.connect(self.queueUrl)
        self.queueFileSignal.connect(self.queueFile)

        self.importQueue.setUrlSignal(self.queueUrlSignal)
        self.importQueue.setFileSignal(self.queueFileSignal)

        self.setForeground()

        self.controller = None
        if JAVA_FOUND:
            threading.Thread(target=self.runController).start()

            # Get core events
            self.controllerGetterTimer = QTimer()
            self.controllerGetterTimer.timeout.connect(self.controllerHandler)
            self.controllerGetterTimer.start(10)
        else:
            message = ("Java not found!\n\nRecommended java: "
                       "<url=\"https://libericajdk.ru/pages/downloads/#/java-8-lts\">"
                       "https://libericajdk.ru/pages/downloads/#/java-8-lts</url>")
            self.showError("Fatal Error:", TextFormatter.format(message, 11), terminate=True)

        InitWindowClose()
        self.__class__.app = self

    def runController(self):
        self.loading.setText("Loading ModLoader Core")

        self.controller = core.Controller()
        self.controller.setModsPath(self.modsPath)
        self.controller.reloadMods()
        self.controller.getModsData()
        self.controller.installBaseMod(f"{PROGRAM_NAME}: {VERSION}")

    def controllerHandler(self):
        if self.controller is None:
            return

        data = self.controller.getData()
        if data is None:
            return

        cmd = data[0]

        if cmd == Environment.Notification:
            notification: core.notifications.Notification = data[1]
            ntype = notification.notificationType

            if ntype == NotificationType.LoadingMod:
                modPath = notification.args[0]
                self.loading.setText(f"Loading mod '{modPath or 'from cache'}'")               
                    
            elif ntype == NotificationType.ModElementsCount:
                modHash, count = notification.args
                self.progressDialog.setMaximum(count)

            # Check conflicts
            elif ntype == NotificationType.ModConflictSearchInSwf:
                modHash, swfName = notification.args
                self.progressDialog.setContent(f"Searching in: {swfName}")
                self.progressDialog.addValue()
            elif ntype == NotificationType.ModConflictNotFound:
                modHash, = notification.args
                self.progressDialog.setValue(0)
                self.controller.installMod(modHash)
            elif ntype == NotificationType.ModConflict:
                modHash, modConflictHashes = notification.args
                self.acceptDialog.setTitle("Conflict mods!")
                content = "Mods:"

                for modConflictHash in modConflictHashes:
                    if modConflictHash in self.mods.mods:
                        mod = self.mods.mods[modConflictHash]
                        content += f"\n- {mod.name}"

                    else:
                        content += f"\n- UNKNOWN MOD: {modConflictHash}"
                        print("ERROR Один из установленных модов не найден в модлодере!")

                self.acceptDialog.setContent(content)
                self.acceptDialog.setAccept(lambda: [self.acceptDialog.hide(), self.controller.installMod(modHash)])
                self.acceptDialog.setCancel(self.acceptDialog.hide)

                self.progressDialog.hide()
                self.acceptDialog.show()


            # Installing
            elif ntype == NotificationType.InstallingModSwf:
                modHash, swfName = notification.args
                self.progressDialog.setContent(f"Open game file: {swfName}")
            elif ntype == NotificationType.InstallingModSwfSprite:
                modHash, sprite = notification.args
                self.progressDialog.setContent(f"Installing sprite: {sprite}")
                self.progressDialog.addValue()
            elif ntype == NotificationType.InstallingModSwfSound:
                modHash, sound = notification.args
                self.progressDialog.setContent(f"Installing sound: {sound}")
                self.progressDialog.addValue()
            elif ntype == NotificationType.InstallingModFile:
                modHash, fileName = notification.args
                self.progressDialog.setContent(f"Installing file: {fileName}")
                self.progressDialog.addValue()
            elif ntype == NotificationType.InstallingModFileCache:
                modHash, fileName = notification.args
                self.progressDialog.setContent(fileName)
                self.progressDialog.addValue()
            elif ntype == NotificationType.InstallingModFinished:
                modHash = notification.args[0]
                modClass = self.mods.mods[modHash]
                modClass.installed = True
                self.mods.updateData()
                self.mods.selectedModButton.updateData()
                self.progressDialog.hide()

                self.showErrorNotifications()

            # Uninstalling
            elif ntype == NotificationType.UninstallingModSwf:
                modHash, swfName = notification.args
                self.progressDialog.setContent(swfName)
            elif ntype == NotificationType.UninstallingModSwfSprite:
                modHash, sprite = notification.args
                self.progressDialog.setContent(sprite)
                self.progressDialog.addValue()
            elif ntype == NotificationType.UninstallingModSwfSound:
                modHash, sprite = notification.args
                self.progressDialog.setContent(sprite)
                self.progressDialog.addValue()
            elif ntype == NotificationType.UninstallingModFile:
                modHash, fileName = notification.args
                self.progressDialog.setContent(fileName)
                self.progressDialog.addValue()
            elif ntype == NotificationType.UninstallingModFinished:
                modHash = notification.args[0]
                modClass = self.mods.mods[modHash]
                modClass.installed = False
                self.mods.updateData()
                self.mods.selectedModButton.updateData()

                self.progressDialog.hide()
                self.showErrorNotifications()

            elif ntype in [NotificationType.CompileModSourcesSpriteHasNoSymbolclass,  # Compiler
                           NotificationType.CompileModSourcesSpriteEmpty,
                           NotificationType.CompileModSourcesSpriteNotFoundInFolder,
                           NotificationType.CompileModSourcesUnsupportedCategory,
                           NotificationType.CompileModSourcesUnknownFile,
                           NotificationType.CompileModSourcesSaveError,
                           NotificationType.LoadingModIsEmpty,  # Loader
                           NotificationType.InstallingModNotFoundFileElement,  # Installer
                           NotificationType.InstallingModNotFoundGameSwf,
                           NotificationType.InstallingModSwfScriptError,
                           NotificationType.InstallingModSwfSoundSymbolclassNotExist,
                           NotificationType.InstallingModSoundNotExist,
                           NotificationType.InstallingModSwfSpriteSymbolclassNotExist,
                           NotificationType.InstallingModSpriteNotExist,
                           NotificationType.UninstallingModSwfOriginalElementNotFound,  # Uninstaller
                           NotificationType.UninstallingModSwfElementNotFound]:
                self.errors.append(notification)

        elif cmd == Environment.ReloadMods:
            self.mods.removeAllMods()

        elif cmd == Environment.GetModsData:
            for modData in data[1]:
                self.mods.addMod(gameVersion=modData.get("gameVersion", ""),
                                 name=modData.get("name", ""),
                                 author=modData.get("author", ""),
                                 version=modData.get("version", ""),
                                 description=modData.get("description", ""),
                                 tags=modData.get("tags", []),
                                 previewsPaths=modData.get("previewsPaths", []),
                                 hash=modData.get("hash", ""),
                                 platform=modData.get("platform", ""),
                                 installed=modData.get("installed", False),
                                 currentVersion=modData.get("currentVersion", False),
                                 modFileExist=modData.get("modFileExist", False))

            self.setModsScreen()
            self.showErrorNotifications()

        elif cmd == Environment.GetModConflict:
            searching, modHash = data[1]
            if searching:
                modClass = self.mods.mods[modHash]
                self.progressDialog.setTitle(f"Searching conflicts '{modClass.name}'...")
                self.progressDialog.setContent("Searching...")
                self.progressDialog.show()

        elif cmd == Environment.InstallMod:
            installing, modHash = data[1]
            if installing:            
                modClass = self.mods.mods[modHash]
                self.progressDialog.setTitle(f"Installing mod '{modClass.name}'...")
                self.progressDialog.setContent("Loading mod...")
                self.progressDialog.show()
                

        elif cmd == Environment.UninstallMod:
            uninstalling, modHash = data[1]
            if uninstalling:
                modClass = self.mods.mods[modHash]
                self.progressDialog.setTitle(f"Uninstalling mod '{modClass.name}'...")
                self.progressDialog.setContent("")
                self.progressDialog.show()

        elif cmd == Environment.DeleteMod:
            pass

        elif cmd == Environment.SetModsPath:
            pass

        elif cmd == Environment.InstallBaseMod:
            self.loading.setText("Installing base mod...")

        else:
            print(f"Controller <- {str(data)}\n", end="")

    def showErrorNotifications(self):
        if self.errors:
            errors = []
            errorsNotifications = self.errors.copy()
            self.errors.clear()

            for notif in errorsNotifications:
                ntype = notif.notificationType
                string = ""

                # Loader
                if ntype == NotificationType.LoadingModIsEmpty:
                    string = f"Mod '{notif.args[1]}' is empty"

                # Installer
                elif ntype == NotificationType.InstallingModNotFoundFileElement:
                    string = f"Not found element '{notif.args[1]}' in bmod "

                elif ntype == NotificationType.InstallingModNotFoundGameSwf:
                    string = f"Not found game file '{notif.args[1]}'"

                elif ntype == NotificationType.InstallingModSwfScriptError:
                    string = f"Script '{notif.args[1]}' not installed"

                elif ntype == NotificationType.InstallingModSwfSoundSymbolclassNotExist:
                    string = f"Not found sound '{notif.args[1]}' in '{notif.args[2]}'"

                elif ntype == NotificationType.InstallingModSoundNotExist:
                    string = f"Not found sound '{notif.args[1]} ({notif.args[2]})' in '{notif.args[3]}'"

                elif ntype == NotificationType.InstallingModSwfSpriteSymbolclassNotExist:
                    string = f"Not found sprite '{notif.args[1]}' in '{notif.args[2]}'"

                elif ntype == NotificationType.InstallingModSpriteNotExist:
                    string = f"Not found sprite '{notif.args[1]} ({notif.args[2]})' in mod file"

                # Uninstaller
                elif ntype == NotificationType.UninstallingModSwfOriginalElementNotFound:
                    string = f"Not found orig element '{notif.args[1]}' in '{notif.args[2]}'"

                elif ntype == NotificationType.UninstallingModSwfElementNotFound:
                    string = f"Not found mod element '{notif.args[1]}' in '{notif.args[2]}'"

                if string:
                    errors.append(string)
                else:
                    errors.append(repr(notif))

            if errors:
                string = ""
                for error in errors:
                    string += f"{error}\n"

                self.showError("Errors:", string)

    @QExecMainThread
    def showError(self, title, content, action=None, terminate=False):
        self.buttonsDialog.setTitle(title)

        if self.acceptDialog.isShown():
            self.acceptDialog.hide()

        if self.buttonsDialog.isShown():
            self.buttonsDialog.hide()

        if self.progressDialog.isShown():
            self.progressDialog.hide()

        if action is None:
            action = self.buttonsDialog.hide

        if terminate:
            action = TerminateApp

        self.buttonsDialog.setContent(content)
        self.buttonsDialog.setButtons([("Copy error", lambda: self.copyToClipboard(f"{title}\n\n{content}")),
                                       ("Ok", action)])
        self.buttonsDialog.show()

    def copyToClipboard(self, text):
        cb = QApplication.clipboard()
        cb.clear(mode=cb.Clipboard)
        cb.setText(text, mode=cb.Clipboard)

    def setLoadingScreen(self):
        ClearFrame(self.ui.mainFrame)
        AddToFrame(self.ui.mainFrame, self.loading)
        self.loading.setText("Loading mods sources...")

    def setModsScreen(self):
        ClearFrame(self.ui.mainFrame)

        AddToFrame(self.ui.mainFrame, self.header)
        AddToFrame(self.ui.mainFrame, self.mods)

    def showInformation(self):
        self.buttonsDialog.setTitle("About")

        string = TextFormatter.table([["Product:", PROGRAM_NAME],
                                      ["Version:", VERSION],
                                      ["GitHub tag:", GIT_VERSION or "None"],
                                      ["Status:", 'Beta' if PRERELEASE else 'Release'],
                                      ["Core version:", CORE_VERSION],
                                      ["Homepage:", f"<url=\"{GITHUB}/{REPO}\">{GITHUB}/{REPO}</url>"],
                                      [None, f"<url=\"{GAMEBANANA}\">{GAMEBANANA}</url>"],
                                      ["Author:", "I_FabrizioG_I"],
                                      ["Contacts:", "Discord: I_FabrizioG_I#8111"],
                                      [None, "VK: vk/fabriziog"]], newLine=False)

        self.buttonsDialog.setContent(TextFormatter.format(string, 11))
        self.buttonsDialog.setButtons([("Ok", self.buttonsDialog.hide)])
        self.buttonsDialog.show()

    def installMod(self):
        if self.mods.selectedModButton is not None:
            modClass = self.mods.selectedModButton.modClass
            self.controller.getModConflict(modClass.hash)

    def uninstallMod(self):
        if self.mods.selectedModButton is not None:
            modClass = self.mods.selectedModButton.modClass
            self.controller.uninstallMod(modClass.hash)

    def reinstallMod(self):
        if self.mods.selectedModButton is not None:
            modClass = self.mods.selectedModButton.modClass
            self.controller.uninstallMod(modClass.hash)
            self.controller.getModConflict(modClass.hash)

    def deleteMod(self):
        if self.mods.selectedModButton is not None:
            modClass = self.mods.selectedModButton.modClass

            self.buttonsDialog.deleteButtons()
            self.buttonsDialog.setTitle(f"Delete mod '{modClass.name}'")

            if modClass.installed:
                self.buttonsDialog.setContent("To delete mod, you need to uninstall it")
            else:
                self.buttonsDialog.setContent("")
                self.buttonsDialog.addButton("Delete", self._deleteMod)

            self.buttonsDialog.addButton("Cancel", self.buttonsDialog.hide)

            self.buttonsDialog.show()

    def reloadMods(self):
        self.setLoadingScreen()
        #self.mods.removeAllMods()
        self.controller.reloadMods()
        self.controller.getModsData()

    def openModsFolder(self):
        os.startfile(self.modsPath)

    def _deleteMod(self):
        modClass = self.mods.selectedModButton.modClass
        modClass.modFileExist = False
        self.controller.deleteMod(modClass.hash)
        self.reloadMods()
        self.buttonsDialog.hide()

    def resizeEvent(self, event):
        self.progressDialog.onResize()
        self.acceptDialog.onResize()
        self.buttonsDialog.onResize()
        super().resizeEvent(event)

    @QExecMainThread
    def newVersion(self, url: str, fileUrl: str, version: str, body: str):
        self.buttonsDialog.setTitle(f"New version available '{version}'")
        self.buttonsDialog.setContent(TextFormatter.format(body, 11))
        self.buttonsDialog.deleteButtons()
        self.buttonsDialog.addButton("GO TO SITE", lambda: webbrowser.open(url))
        self.buttonsDialog.addButton("UPDATE", lambda: [self.buttonsDialog.hide(),
                                                        self.updateApp(fileUrl, version)])
        self.buttonsDialog.addButton("CANCEL", self.buttonsDialog.hide)
        self.buttonsDialog.show()

    def handleUpdateApp(self, blocknum, blocksize, totalsize):
        readedData = blocknum * blocksize

        if totalsize > 0:
            downloadPercentage = int(readedData * 100 / totalsize)
            self.progressDialog.setValue(downloadPercentage)
            QApplication.processEvents()

    def updateApp(self, fileUrl: str, version: str):
        filePath = os.path.join(os.getcwd(), "temp.exe")
        fileName = os.path.split(fileUrl)[1]

        self.progressDialog.setMaximum(100)
        self.progressDialog.setTitle(f"Update ModLoader to '{version}'")
        self.progressDialog.setContent(f"Download '{fileName}'")
        self.progressDialog.show()
        urllib.request.urlretrieve(fileUrl, filePath, self.handleUpdateApp)
        self.progressDialog.hide()

        subprocess.Popen([os.environ["CLIENT_PATH"], "-update",
                         os.path.abspath(sys.argv[0]),
                         filePath])
        QApplication.exit(0)

    def checkNewVersion(self):
        latest = GetLatest()

        if latest is not None:
            newVersion, fileUrl, version, body = latest
            self.newVersion(newVersion, fileUrl, version, body)

    @QExecMainThread
    def setForeground(self):
        try:
            if sys.platform.startswith("win"):
                import win32gui, win32com.client

                shell = win32com.client.Dispatch("WScript.Shell")
                shell.SendKeys('%')
                win32gui.SetForegroundWindow(self.winId())
        except:
            pass

    queueFileSignal = Signal()

    def queueFile(self):
        for file in self.importQueue.iterFile():
            self.fileImport(file)

    def fileImport(self, filePath: str):
        self.setForeground()

        if os.path.abspath(filePath).startswith(os.path.abspath(self.modsPath)):
            return

        fileName = os.path.split(filePath)[1]
        fileNameSplit = os.path.splitext(fileName)

        if os.path.exists(os.path.join(self.modsPath, fileName)):
            i = 1
            while os.path.exists(os.path.join(self.modsPath, f"{fileNameSplit[0]} ({i}){fileNameSplit[1]}")):
                i += 1
            fileName = f"{fileNameSplit[0]} ({i}){fileNameSplit[1]}"

        with open(filePath, "rb") as outsideMod:
            with open(os.path.join(self.modsPath, fileName), "wb") as insideMod:
                insideMod.write(outsideMod.read())

        self.reloadMods()

    queueUrlSignal = Signal()

    def queueUrl(self):
        for url in self.importQueue.iterUrl():
            self.urlImport(url)

    def urlImport(self, url: str):
        self.setForeground()

        data = url.split(":", 1)[1].strip("/")
        splitData = data.split(",")

        if len(splitData) == 3:
            tag, modId, dlId = data.split(",")
            zipUrl = f"http://gamebanana.com/dl/{dlId}"
        else:
            zipUrl = ""
            return

        archivePath = os.path.join(self.modsPath, "_mod.archive")

        self.progressDialog.setMaximum(100)
        self.progressDialog.setTitle("Download mod")
        self.progressDialog.setContent("")
        self.progressDialog.show()
        QApplication.processEvents()
        try:
            urllib.request.urlretrieve(zipUrl, archivePath, self.handleUpdateApp)

            with open(archivePath, "rb") as file:
                _signature = file.read(3)

            if _signature.startswith(b"7z"):
                with py7zr.SevenZipFile(archivePath) as mod7z:
                    for file in mod7z.getnames():
                        if file.endswith(f".{core.MOD_FILE_FORMAT}"):
                            self.progressDialog.setContent(f"Extract: '{file}'")
                            QApplication.processEvents()
                            mod7z.extract(self.modsPath, [file])

            elif _signature.startswith(b"Rar"):
                with rarfile.RarFile(archivePath) as modRar:
                    for file in modRar.namelist():
                        if file.endswith(f".{core.MOD_FILE_FORMAT}"):
                            self.progressDialog.setContent(f"Extract: '{file}'")
                            QApplication.processEvents()
                            modRar.extract(file, self.modsPath)

            elif _signature.startswith(b"PK"):
                with zipfile.ZipFile(archivePath) as modZip:
                    for file in modZip.namelist():
                        if file.endswith(f".{core.MOD_FILE_FORMAT}"):
                            self.progressDialog.setContent(f"Extract: '{file}'")
                            QApplication.processEvents()
                            modZip.extract(file, self.modsPath)

            self.reloadMods()
            self.progressDialog.hide()

        except rarfile.RarCannotExec:
            self.showError("Unpack error:", "WinRar 'unrar.exe' not found")

        except:
            self.showError("Unpack error:", "".join(traceback.format_exception(*sys.exc_info())))

        finally:
            os.remove(archivePath)


# pyrcc5 -o ui/ui_sources/icons_rc.py ui/ui_sources/icons.qrc
# venv\Lib\site-packages\PySide6\lupdate.exe @ui/ui_sources/ui_files.txt -ts ui/ui_sources/translate/header/ru_RU.ts
# venv\Lib\site-packages\PySide6\lupdate.exe ui/ui_sources/header.ui -locations ui/ui_sources/translate/header
# venv\Lib\site-packages\PySide6\lrelease.exe E:\BrawlhallaModloaderApp_0.3\ui\ui_sources\translate\header\ru_RU.ts


def RunApp():
    app = QApplication(sys.argv)

    font_db = QFontDatabase()
    font_db.addApplicationFont(":/fonts/resources/fonts/Exo 2/Exo2-SemiBold.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-Black.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-BlackItalic.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-Bold.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-BoldItalic.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-Italic.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-Medium.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-MediumItalic.ttf")
    font_db.addApplicationFont(":/fonts/resources/fonts/Roboto/Roboto-Regular.ttf")

    """
    translator = QTranslator()
    lang = QLocale.system().name()
    supportedLangs = translate.GetLangs()
    if lang in supportedLangs:
        translator.load(supportedLangs[lang])
    app.installTranslator(translator)
    """

    window = ModLoader()
    window.show()
    window.showError("Important Information", "Please remember that ALL SKIN MODS require a PAID SKIN to work.\nBe sure to read the Brawlhalla Modding Community rules first!")
    webbrowser.open_new("https://gamebanana.com/games/rules/5704")
    exitId = app.exec()
    TerminateApp(exitId)


if __name__ == "__main__":
    RunApp()
