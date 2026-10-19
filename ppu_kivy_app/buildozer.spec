# Сборка APK «Помощник ППУ».
#
# Buildozer + python-for-android работают ТОЛЬКО под Linux. На Windows — собираем в WSL2:
#
#   1) Windows (PowerShell от администратора):  wsl --install -d Ubuntu-22.04
#   2) Ubuntu (WSL2):
#        sudo apt update
#        sudo apt install -y git zip unzip openjdk-17-python3 python3-pip python3-setuptools \
#            autoconf libtool pkg-config zlib1g-dev libncurses5-dev libglib2.0-dev \
#            libx11-dev libssl-dev cmake maven
#        pip3 install --user --upgrade pip cython buildozer
#   3) Копируем проект в WSL (credentials.json в APK НЕ кладём!):
#        cp -r /mnt/d/Qoder/ppu_bot_TG_only/ppu_kivy_app ~/ppu_kivy_app
#   4) Сборка отладочного APK:
#        cd ~/ppu_kivy_app
#        buildozer android debug
#        # результат: bin/*-debug.apk  (ставится на телефон разрешением на неизвестные источники)
#
#   Первая сборка скачивает Android SDK/NDK — несколько гигабайт, 20–60 минут.
#   Отладка на телефоне:  buildozer android debug deploy run logcat
#

[APP]

title = Помощник ППУ
package.name = ppupomoshnik
package.domain = org.ppu
version = 1.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,json
source.exclude_dirs = app_data, app_data_ui, bin, build, tests, tools, __pycache__, .idea
source.exclude_exts = spec, log, md, lock

# google-auth и requests — чистый Python, но python-for-android НЕ подтягивает их
# зависимости автоматически, поэтому все перечислены явно.
requirements = python3,kivy==2.3.1,openssl,pyjnius,requests,urllib3,idna,charset_normalizer,certifi,google-auth,cachetools,rsa,pyasn1,pyasn1_modules,six

orientation = portrait
fullscreen = 0

# ACTION_DIAL (звонок через системный номеронабиратель) не требует CALL_PHONE.
# READ_EXTERNAL_STORAGE нужен FileChooser-у, чтобы достать credentials.json из папок телефона.
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True

# release-сборка (подпишите своим keystore): android.release = 1
android.release = 0

icon.filename = %(source)s/icon.png
presplash.filename = %(source)s/presplash.png

# логи python-части на устройстве
logcat_filter = python:V,*:I

[BUILDERS]

[INSTALL]
