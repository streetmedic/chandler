;
;   Copyright (c) 2004-2007 Open Source Applications Foundation
;
;   Licensed under the Apache License, Version 2.0 (the "License");
;   you may not use this file except in compliance with the License.
;   You may obtain a copy of the License at
;
;       http://www.apache.org/licenses/LICENSE-2.0
;
;   Unless required by applicable law or agreed to in writing, software
;   distributed under the License is distributed on an "AS IS" BASIS,
;   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
;   See the License for the specific language governing permissions and
;   limitations under the License.

; Script initially generated by the HM NIS Edit Script Wizard,
; but it's been long ago mangled beyond recognition by bear

!ifdef SNAP_DEBUG
  !define PRODUCT_BINARY "chandlerDebug.exe"
  !define SNAP "debug"
!else
  !define PRODUCT_BINARY "chandler.exe"
  !define SNAP "release"
!endif

!define PRODUCT_NAME "Chandler"
!define PRODUCT_VERSION "${DISTRIB_VERSION}"
!define PRODUCT_PUBLISHER "Open Source Applications Foundation"
!define PRODUCT_WEB_SITE "http://osafoundation.org"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\${PRODUCT_NAME}"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

SetCompressor lzma

; MUI = Modern User Interface
; It's a set of macros and dialogs that makes NSIS look and feel
; like an "normal" windows installer

; MUI 1.67 compatible
!include "MUI.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

; Establish which pages, and in what order, will be displayed to the user
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
Page custom PageReinstall PageLeaveReinstall
Page custom PageOldVersion
!insertmacro MUI_PAGE_INSTFILES

InstallDir "$PROGRAMFILES\${PRODUCT_NAME}${PRODUCT_VERSION}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""

!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_BINARY}"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.win.txt"

; establish a custom function that runs before the finish page
!define MUI_PAGE_CUSTOMFUNCTION_PRE "change_cancel_text"

!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_INSTFILES

; Language files
!insertmacro MUI_LANGUAGE "English"

; MUI end ------

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "Setup.exe"
Icon "..\..\..\${DISTRIB_DIR}\Chandler.egg-info\resources\icons\Chandler.ico"
UninstallIcon "..\..\..\${DISTRIB_DIR}\Chandler.egg-info\resources\icons\Chandler.ico"
ShowInstDetails nevershow
ShowUnInstDetails nevershow

Function .onInit

    ;  global variable warning!
    ;  $R8 is defined here and used in two spots in this script
    ;  $R8 = "true" if the install program is being run by someone with admin privs

  Call IsUserAdmin
  pop $R8

  ; look for another instance of the installer and
  ; if found, bring it to the front
  ;
  ; a mutex is created using a known key - if any other
  ; instance of the installer is running then the mutex
  ; creation will fail

  System::Call "kernel32::CreateMutexA(i 0, i 0, t '$(^Name)') i .r0 ?e"

  Pop $0                ; grab return value from CreateMutex
  StrCmp $0 0 launch    ; jump to "launch" if mutex creation was successful
  StrLen $0 "$(^Name)"  ; Find length of app name and
  IntOp $0 $0 + 1       ;   pad the length by one

    ; loop thru the list of active windows - if we find ours bring it to the front
  loop:
    FindWindow $1 '#32770' '' 0 $1      ; get window name and store into $1
    IntCmp $1 0 +4                      ; no more windows - jump to "launch" (+4 lines)
    System::Call "user32::GetWindowText(i r1, t .r2, i r0) i."
    StrCmp $2 "$(^Name)" 0 loop         ; is the title from GetWindowText call above ours?
    System::Call "user32::SetForegroundWindow(i r1) i."   ; yes? bring it to the front
    Abort
  launch:

  !insertmacro MUI_INSTALLOPTIONS_EXTRACT_AS "uninstall_dialog.ini" "uninstall_dialog.ini"
  !insertmacro MUI_INSTALLOPTIONS_EXTRACT_AS "oldversion_dialog.ini" "oldversion_dialog.ini"

FunctionEnd

Function change_cancel_text

  !insertmacro MUI_INSTALLOPTIONS_WRITE "ioSpecial.ini" "Settings" "CancelEnabled" "0"

FunctionEnd

Function PageReinstall

    ; if the installer is running as a non-admin user ("normal user")
    ; then the uninstall program will be found in the HKCU registry root
    ; otherwise it will be in HKLM

  ;MessageBox MB_ICONINFORMATION|MB_OK "0 [$INSTDIR] [${PRODUCT_NAME}][${PRODUCT_VERSION}]"

  StrCmp $R8 "true" 0 normal_user
  ReadRegStr $R9 HKLM "${PRODUCT_UNINST_KEY}" "UninstallString"
  goto check_uninstall

  normal_user:
  ReadRegStr $R9 HKCU "${PRODUCT_UNINST_KEY}" "UninstallString"

  check_uninstall:
  StrCpy $R3 ""
  
  StrLen $R1 $R9        ; get length of uninstall string
  IntOp  $R1 $R1 - 11   ; adjust length to only include the path
  StrCpy $R0 $R9 $R1    ; extract path from the uninstall string

  ;MessageBox MB_ICONINFORMATION|MB_OK "1 [$R0]"

  IfFileExists $R9 0 check_instdir
  
  StrCpy $R3 $R0

  ;MessageBox MB_ICONINFORMATION|MB_OK "2 [$R0] [$R9] [$R3]"

  check_instdir:
    StrCpy $R1 $INSTDIR
    StrCpy $R5 "$R1\uninst.exe"

    ;MessageBox MB_ICONINFORMATION|MB_OK "[$R5] [$R1]"

    IfFileExists $R5 0 build_msg

    StrCpy $R3 "$R3$R1"

  build_msg:
    ;MessageBox MB_ICONINFORMATION|MB_OK "3 [$R1] [$R3]"

    StrCmp $R3 "" 0 compare_dirs
    Abort

  compare_dirs:
    StrCmp $R0 "" only_instdir

    StrCmp $R0 $R1 0 diff_dir

  only_instdir:
    StrCpy $R2 $R1
  
    Goto display_dialog
  
  diff_dir:
    StrCpy $R2 "$R0 and $R1"

    ;MessageBox MB_ICONINFORMATION|MB_OK "4 [$R2]"

  display_dialog:
    !insertmacro MUI_HEADER_TEXT "Chandler is already installed" "Chandler is already installed on your system ($R2)."
    !insertmacro MUI_INSTALLOPTIONS_DISPLAY "uninstall_dialog.ini"

FunctionEnd

Function PageLeaveReinstall

    ; get from the uninstall dialog the option selected

  !insertmacro MUI_INSTALLOPTIONS_READ $R1 "uninstall_dialog.ini" "Field 2" "State"
  StrCmp $R1 "1" uninstall_chandler do_nothing

  uninstall_chandler:
    ;MessageBox MB_ICONINFORMATION|MB_OK "u1 [$R9]"

    IfFileExists $R9 0 check_instdir  ; check install dir if normal uninstall is not found

      StrLen $R2 $R9        ; get length of uninstall string
      IntOp  $R2 $R2 - 10   ; adjust length to only include the path
      StrCpy $R0 $R9 $R2    ; extract path from the uninstall string

      ;MessageBox MB_ICONINFORMATION|MB_OK "u2 [$R0] [$R9]"

      HideWindow
      ClearErrors

      ExecWait '$R9 _?=$R0' ; run uninstall program (set current dir to install dir)

      IfErrors uninstall_failed
      IfFileExists "$R0\chandler.exe" uninstall_failed    ; sanity check to see if uninstall failed

      ;Delete $R9            ; clean up by removing uninstall program
      ;RMDIR $INSTDIR        ; and then remove the should-be empty install directory

      Goto do_nothing

    check_instdir:
      StrCpy $R9 "$INSTDIR\uninst.exe"

      ;MessageBox MB_ICONINFORMATION|MB_OK "u3 [$R9]"

      IfFileExists $R9 0 do_nothing

      ;MessageBox MB_ICONINFORMATION|MB_OK "u4 [$R9]"

      HideWindow
      ClearErrors

      ExecWait '$R9 _?=$INSTDIR' ; run uninstall program (set current dir to install dir)

      IfErrors uninstall_failed
      IfFileExists "$INSTDIR\chandler.exe" uninstall_failed    ; sanity check to see if uninstall failed

      ;Delete $R9            ; clean up by removing uninstall program
      ;RMDIR $INSTDIR        ; and then remove the should-be empty install directory

    Goto do_nothing

  uninstall_failed:
    MessageBox MB_ICONINFORMATION|MB_OK "An error occured while un-installing $(^Name).  You will need to manually remove it before proceeding."
    Quit

  do_nothing:
    StrCpy $R9 "bypass"   ; set $R9 so the oldversion dialog is skipped

    ;MessageBox MB_ICONINFORMATION|MB_OK "u5 [$R9]"

    BringToFront          ; since the user has requested to continue with the install

FunctionEnd

Function PageOldVersion

      ; check to see if the previous version check was run and the user selected "continue"
      ; and if so, don't check for an older version as we already know there is one
    StrCmp $R9 "bypass" nothing_to_remove

      ; The only way to get here is for the previous version un-install to leave behind
      ; the chandler.exe or for there to be a really old version present

    StrCpy $R5 "$INSTDIR\chandler.exe"
    IfFileExists $R5 display_dialog nothing_to_remove

  nothing_to_remove:
    Abort

  display_dialog:
    !insertmacro MUI_HEADER_TEXT "Chandler is already installed" "An older version of Chandler is located at $INSTDIR."
    !insertmacro MUI_INSTALLOPTIONS_DISPLAY "oldversion_dialog.ini"

FunctionEnd


; Copied from http://nsis.sourceforge.net/IsUserAdmin
;
; Author: Lilla (lilla@earthlink.net) 2003-06-13
; function IsUserAdmin uses plugin \NSIS\PlusgIns\UserInfo.dll
; This function is based upon code in \NSIS\Contrib\UserInfo\UserInfo.nsi
; This function was tested under NSIS 2 beta 4 (latest CVS as of this writing).
;
; Usage:
;   Call IsUserAdmin
;   Pop $R0   ; at this point $R0 is "true" or "false"
;
Function IsUserAdmin
Push $R0
Push $R1
Push $R2
 
ClearErrors
UserInfo::GetName
IfErrors Win9x
Pop $R1
UserInfo::GetAccountType
Pop $R2
 
StrCmp $R2 "Admin" 0 Continue
; Observation: I get here when running Win98SE. (Lilla)
; The functions UserInfo.dll looks for are there on Win98 too, 
; but just don't work. So UserInfo.dll, knowing that admin isn't required
; on Win98, returns admin anyway. (per kichik)
; MessageBox MB_OK 'User "$R1" is in the Administrators group'
StrCpy $R0 "true"
Goto Done
 
Continue:
; You should still check for an empty string because the functions
; UserInfo.dll looks for may not be present on Windows 95. (per kichik)
StrCmp $R2 "" Win9x
StrCpy $R0 "false"
;MessageBox MB_OK 'User "$R1" is in the "$R2" group'
Goto Done
 
Win9x:
; comment/message below is by UserInfo.nsi author:
; This one means you don't need to care about admin or
; not admin because Windows 9x doesn't either
;MessageBox MB_OK "Error! This DLL can't run under Windows 9x!"
StrCpy $R0 "true"
 
Done:
;MessageBox MB_OK 'User= "$R1"  AccountType= "$R2"  IsUserAdmin= "$R0"'
 
Pop $R2
Pop $R1
Exch $R0
FunctionEnd

Section "MainSection" SEC01
  SetOutPath "$INSTDIR"
  File "..\..\..\${DISTRIB_DIR}\*.py"
  File "..\..\..\${DISTRIB_DIR}\${PRODUCT_BINARY}"
  File "..\..\..\${DISTRIB_DIR}\LICENSE.txt"
  File "..\..\..\${DISTRIB_DIR}\README.win.txt"

    ; this could be handled completely by the above line
    ; if the /r option was used - I kept them as individual
    ; items to better document what sub-folders are included
    ; NOTE: any File entry added here also needs to be added 
    ;       to the uninstall section below
    
  File /r "..\..\..\${DISTRIB_DIR}\application"
  File /r "..\..\..\${DISTRIB_DIR}\${SNAP}"
  File /r "..\..\..\${DISTRIB_DIR}\Chandler.egg-info"
  File /r "..\..\..\${DISTRIB_DIR}\i18n"
  File /r "..\..\..\${DISTRIB_DIR}\parcels"
  File /r "..\..\..\${DISTRIB_DIR}\util"
  File /r "..\..\..\${DISTRIB_DIR}\tools"
  File /r "..\..\..\${DISTRIB_DIR}\plugins"

  CreateDirectory "$SMPROGRAMS\Chandler"
  CreateShortCut "$SMPROGRAMS\Chandler\Chandler.lnk" "$INSTDIR\${PRODUCT_BINARY}" "" "$INSTDIR\Chandler.egg-info\resources\icons\Chandler.ico" 
  CreateShortCut "$DESKTOP\Chandler.lnk" "$INSTDIR\${PRODUCT_BINARY}" "" "$INSTDIR\Chandler.egg-info\resources\icons\Chandler.ico"
SectionEnd

  ; create the uninstall shortcut - done here so that it will only
  ; be created *if* the install was successful
  
Section -AdditionalIcons
  CreateShortCut "$SMPROGRAMS\Chandler\Uninstall.lnk" "$INSTDIR\uninst.exe"
SectionEnd

  ; post install steps - add Chandler to the add/remove programs registry list
  
Section -Post
  WriteUninstaller "$INSTDIR\uninst.exe"

    ; if the installer is running as a non-admin user ("normal user")
    ; then the we need to write the program and uninstall registry values
    ; to the HKCU registry root, otherwise write them to the HKLM root

  StrCmp $R8 "true" 0 normal_user
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_BINARY}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  
  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\${PRODUCT_BINARY}"
  WriteRegStr HKLM "Software\OSAF" "Version" "${PRODUCT_VERSION}"

  goto post_done

  normal_user:
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_BINARY}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  
  WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\${PRODUCT_BINARY}"
  WriteRegStr HKCU "Software\OSAF" "Version" "${PRODUCT_VERSION}"

  post_done:

SectionEnd

Function un.onUninstSuccess
  HideWindow
  MessageBox MB_ICONINFORMATION|MB_OK "$(^Name) was successfully removed from your computer."
FunctionEnd

Function un.onInit
  MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "Are you sure you want to completely remove $(^Name) and all of its components?" IDYES +2
  Abort
FunctionEnd

  ; this section controls exactly what parts of Chandler are removed
  ; currently *all* directories are removed

Section Uninstall
  Delete "$INSTDIR\uninst.exe"
  Delete "$SMPROGRAMS\Chandler\Uninstall.lnk"
  Delete "$DESKTOP\Chandler.lnk"
  Delete "$SMPROGRAMS\Chandler\Chandler.lnk"

  RMDir "$SMPROGRAMS\Chandler"

  RMDir /r "$INSTDIR\application"
  RMDir /r "$INSTDIR\crypto"
  RMDir /r "$INSTDIR\${SNAP}"
  RMDir /r "$INSTDIR\Chandler.egg-info"
  RMDir /r "$INSTDIR\i18n"
  RMDir /r "$INSTDIR\parcels"
  RMDir /r "$INSTDIR\util"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\plugins"

  Delete "$INSTDIR\*.*"

  RMDir "$INSTDIR"

  StrCmp $R8 "true" 0 un_normal_user

  DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
  DeleteRegKey HKLM "Software\OSAF"
  goto continue_uninstall

  un_normal_user:
  DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKCU "${PRODUCT_DIR_REGKEY}"
  DeleteRegKey HKCU "Software\OSAF"

  continue_uninstall:
  SetAutoClose true
SectionEnd
