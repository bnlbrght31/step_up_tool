-- SUFS Agent.app — opens the launcher in Terminal (which starts the app + Chrome)
-- The path is built from the home folder, so no username is written into the source.
set launcher to POSIX path of (path to home folder) & "Desktop/claude/step_up_tool/launch.command"
do shell script "open " & quoted form of launcher
