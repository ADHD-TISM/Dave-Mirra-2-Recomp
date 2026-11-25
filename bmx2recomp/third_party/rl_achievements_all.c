/* Recomp Achievements (rl_achievements/, Recomp Achievements License 1.0; rcheevos and cJSON MIT) built as
 * one file, like libchdr_all.c. Include paths (build.sh and the launcher's _flags):
 *   -I third_party/rl_achievements/include
 *   -I third_party/rl_achievements/third_party/rcheevos/include
 *   -I third_party/rl_achievements/third_party/rcheevos/src
 *   -I third_party/rl_achievements/third_party/cjson   -D RC_DISABLE_LUA
 * The library's files are unchanged. */
#include "rl_achievements/third_party/cjson/cJSON.c"
#include "rl_achievements/third_party/rcheevos/src/util/md5.c"
#include "rl_achievements/third_party/rcheevos/src/util/rc_compat.c"
#include "rl_achievements/third_party/rcheevos/src/util/rc_util.c"
#include "rl_achievements/third_party/rcheevos/src/util/rc_version.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_alloc.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_condition.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_condset.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_consoleinfo.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_format.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_lboard.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_memref.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_operand.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_richpresence.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_runtime.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_runtime_progress.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_trigger.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_typed_value.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_validate.c"
#include "rl_achievements/third_party/rcheevos/src/runtime/rc_value.c"
#include "rl_achievements/src/rl_achievements.c"
