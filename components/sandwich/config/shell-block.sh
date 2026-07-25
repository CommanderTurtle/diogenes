# >>> sandwich >>>
export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export BUN_INSTALL_BIN="${BUN_INSTALL_BIN:-$BUN_INSTALL/bin}"
export BUN_INSTALL_GLOBAL_DIR="${BUN_INSTALL_GLOBAL_DIR:-$BUN_INSTALL/install/global}"
export DO_NOT_TRACK=1

sandwich_prepend_path() {
    case ":$PATH:" in
        *":$1:"*) ;;
        *) PATH="$1:$PATH" ;;
    esac
}
sandwich_prepend_path "$BUN_INSTALL_BIN"
sandwich_prepend_path "$HOME/.local/bin"
export PATH
unset -f sandwich_prepend_path
# <<< sandwich <<<
