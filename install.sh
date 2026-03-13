#!/bin/bash

# Цвета для красивого вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}┌────────────────────────────────────┐${NC}"
echo -e "${BLUE}│  ${GREEN}Установка Cherkashka Bot${BLUE}            │${NC}"
echo -e "${BLUE}└────────────────────────────────────┘${NC}"
echo ""

# Проверяем, что это Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo -e "${RED}❌ Ошибка: Этот скрипт предназначен только для Linux${NC}"
    exit 1
fi

# Определяем дистрибутив
if command -v pacman &> /dev/null; then
    DISTRO="arch"
    echo -e "${GREEN}✓ Обнаружен Arch Linux / EndeavourOS${NC}"
elif command -v apt &> /dev/null; then
    DISTRO="debian"
    echo -e "${GREEN}✓ Обнаружен Debian/Ubuntu${NC}"
elif command -v dnf &> /dev/null; then
    DISTRO="fedora"
    echo -e "${GREEN}✓ Обнаружен Fedora${NC}"
else
    echo -e "${YELLOW}⚠️ Не удалось определить дистрибутив${NC}"
    DISTRO="unknown"
fi

# Проверяем наличие git
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}⚠️ Git не найден. Устанавливаем...${NC}"
    case $DISTRO in
        arch)
            sudo pacman -S git --noconfirm
            ;;
        debian)
            sudo apt update && sudo apt install git -y
            ;;
        fedora)
            sudo dnf install git -y
            ;;
        *)
            echo -e "${RED}❌ Пожалуйста, установите git вручную${NC}"
            exit 1
            ;;
    esac
fi

# Проверяем наличие python3
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}⚠️ Python3 не найден. Устанавливаем...${NC}"
    case $DISTRO in
        arch)
            sudo pacman -S python --noconfirm
            ;;
        debian)
            sudo apt update && sudo apt install python3 python3-pip python3-venv -y
            ;;
        fedora)
            sudo dnf install python3 python3-pip -y
            ;;
        *)
            echo -e "${RED}❌ Пожалуйста, установите python3 вручную${NC}"
            exit 1
            ;;
    esac
fi

# Создаем директорию для установки
INSTALL_DIR="$HOME/.local/share/cherkashka-bot"
BIN_DIR="$HOME/.local/bin"

echo -e "${GREEN}📁 Установка в: $INSTALL_DIR${NC}"

# Клонируем или копируем файлы
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}⚠️ Директория уже существует. Обновляем...${NC}"
    # Сохраняем старые данные
    if [ -f "$INSTALL_DIR/.env" ]; then
        cp "$INSTALL_DIR/.env" /tmp/.env.backup
    fi
    if [ -f "$INSTALL_DIR/user_balances.json" ]; then
        cp "$INSTALL_DIR/user_balances.json" /tmp/user_balances.json.backup
    fi
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"

# Копируем файлы из текущей папки (если скрипт запускается из репозитория)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"

# Восстанавливаем данные, если были
if [ -f "/tmp/.env.backup" ]; then
    cp "/tmp/.env.backup" "$INSTALL_DIR/.env"
    echo -e "${GREEN}✓ Восстановлен .env из бэкапа${NC}"
fi
if [ -f "/tmp/user_balances.json.backup" ]; then
    cp "/tmp/user_balances.json.backup" "$INSTALL_DIR/user_balances.json"
    echo -e "${GREEN}✓ Восстановлен баланс из бэкапа${NC}"
fi

cd "$INSTALL_DIR"

# Создаем виртуальное окружение
echo -e "${GREEN}🐍 Создаем виртуальное окружение...${NC}"
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
echo -e "${GREEN}📦 Устанавливаем зависимости...${NC}"
pip install --upgrade pip
pip install aiogram python-dotenv requests yoomoney

# Создаем пример .env файла если его нет
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚙️ Создаем файл .env.example${NC}"
    cat > .env.example << 'EOF'
# Telegram Bot Token (получи у @BotFather)
BOT_TOKEN=твой_токен_бота

# Твой Telegram ID (админ)
OWNER_ID=1970387854

# CryptoBot (опционально)
CRYPTOBOT_API_TOKEN=токен_cryptobot

# TON (опционально)
TON_DEPOSIT_ADDRESS=адрес_кошелька_ton
TON_API_KEY=ключ_ton_api

# ЮMoney (опционально)
YOOMONEY_RECEIVER=номер_кошелька
YOOMONEY_TOKEN=токен_юmoney
EOF
    echo -e "${YELLOW}⚠️ Скопируйте .env.example в .env и заполните токены${NC}"
fi

# Делаем start.sh исполняемым
chmod +x start.sh 2>/dev/null || true

# Создаем исполняемый файл в ~/.local/bin
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/cherkashka-bot" << 'EOF'
#!/bin/bash
cd "$HOME/.local/share/cherkashka-bot"
source venv/bin/activate
python Cherkashka.py "$@"
EOF

chmod +x "$BIN_DIR/cherkashka-bot"

# Проверяем PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "${YELLOW}⚠️ Добавьте ~/.local/bin в PATH, выполнив:${NC}"
    echo '  echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> ~/.bashrc'
    echo '  source ~/.bashrc'
    echo ""
    echo -e "${YELLOW}Или запускайте бота напрямую:${NC}"
    echo "  $INSTALL_DIR/start.sh"
fi

echo -e "${GREEN}┌────────────────────────────────────┐${NC}"
echo -e "${GREEN}│  ✅ Установка завершена!            │${NC}"
echo -e "${GREEN}└────────────────────────────────────┘${NC}"
echo ""
echo -e "${BLUE}📝 Команды для запуска:${NC}"
echo "  cherkashka-bot              # если ~/.local/bin в PATH"
echo "  $INSTALL_DIR/start.sh        # или напрямую"
echo ""
echo -e "${BLUE}⚙️  Настройка:${NC}"
echo "  nano $INSTALL_DIR/.env       # отредактируй токены"
echo ""
echo -e "${BLUE}📊 Файлы с данными:${NC}"
echo "  $INSTALL_DIR/user_balances.json"
echo "  $INSTALL_DIR/transaction_history.json"
echo "  $INSTALL_DIR/user_prizes.json"
echo ""
echo -e "${YELLOW}После редактирования .env запусти бота!${NC}"
