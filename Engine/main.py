from pathlib import Path
import argparse
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


class PhonemeClass:
    def __init__(self, name, symbol, phonemes):
        self.name = name
        self.symbol = symbol
        self.phonemes = phonemes

    def contains(self, value):
        return value in self.phonemes


class Phonology:
    def __init__(self, path):
        self.path = path
        self.classes = {}
        self.load()

    def load(self):
        if not self.path.exists():
            raise FileNotFoundError(
                f"Phonology file not found: {self.path}"
            )

        text = self.path.read_text(
            encoding="utf-8"
        )

        pattern = re.compile(
            r"^##\s+(.+?)\s+\$\s*"
            r"([A-Za-z][A-Za-z0-9_]*)\s*$",
            re.MULTILINE
        )

        matches = list(
            pattern.finditer(text)
        )

        for index, match in enumerate(matches):
            name = match.group(1).strip()
            symbol = "$" + match.group(2).strip()

            start = match.end()

            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(text)
            )

            content = text[start:end]
            phonemes = self.parsePhonemes(
                content
            )

            if not phonemes:
                raise ValueError(
                    f"Phoneme class {symbol} "
                    "has no phonemes."
                )

            if symbol in self.classes:
                raise ValueError(
                    f"Duplicate phoneme class "
                    f"symbol: {symbol}"
                )

            self.classes[symbol] = PhonemeClass(
                name,
                symbol,
                phonemes
            )

    def parsePhonemes(self, content):
        phonemes = []

        for line in content.splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("<!--"):
                continue

            if line.startswith("#"):
                continue

            if line.startswith("-"):
                line = line[1:].strip()

            phonemes.extend(
                line.split()
            )

        return phonemes

    def get(self, symbol):
        if symbol not in self.classes:
            raise ValueError(
                f"Unknown phoneme class: {symbol}"
            )

        return self.classes[symbol]

    def symbols(self):
        return list(
            self.classes.keys()
        )


class Rule:
    def __init__(self, text):
        self.text = text
        self.source = ""
        self.target = ""
        self.leftContext = ""
        self.rightContext = ""
        self.parse()

    def parse(self):
        if "?" in self.text:
            left, context = (
                self.text.split("?", 1)
            )
        else:
            left = self.text
            context = ""

        if "→" not in left:
            if ">" in left:
                left = left.replace(
                    ">",
                    "→",
                    1
                )
            else:
                raise ValueError(
                    f"Invalid rule: {self.text}"
                )

        source, target = left.split(
            "→",
            1
        )

        self.source = source.strip()
        self.target = target.strip()

        context = context.strip()

        if "_" in context:
            leftContext, rightContext = (
                context.split("_", 1)
            )
        else:
            leftContext = ""
            rightContext = ""

        self.leftContext = (
            leftContext.strip()
        )

        self.rightContext = (
            rightContext.strip()
        )

        if not self.source:
            raise ValueError(
                f"Rule has no source: "
                f"{self.text}"
            )

        if not self.target:
            raise ValueError(
                f"Rule has no target: "
                f"{self.text}"
            )


class Change:
    def __init__(
        self,
        changeId,
        name,
        stage,
        path,
        rules
    ):
        self.id = changeId
        self.name = name
        self.stage = stage
        self.path = path
        self.rules = rules

        try:
            self.order = int(changeId)
        except ValueError:
            self.order = 10**9


class Lexeme:
    def __init__(
        self,
        path,
        metadata,
        body,
        proto,
        current
    ):
        self.path = path
        self.metadata = metadata
        self.body = body
        self.proto = proto
        self.current = current


class Engine:
    def __init__(self, root):
        self.root = root
        self.lexiconDir = (
            root / "Lexicon"
        )
        self.changesDir = (
            root / "Changes"
        )
        self.phonologyFile = (
            root
            / "Core"
            / "Phonology.md"
        )

        self.phonology = Phonology(
            self.phonologyFile
        )

    def readMarkdown(self, path):
        return path.read_text(
            encoding="utf-8"
        )

    def parseFrontmatter(self, text):
        if not text.startswith("---"):
            return {}, text

        lines = text.splitlines()
        end = None

        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end = index
                break

        if end is None:
            return {}, text

        data = {}

        for line in lines[1:end]:
            if (
                not line.strip()
                or ":" not in line
            ):
                continue

            key, value = line.split(
                ":",
                1
            )

            key = key.strip()
            value = value.strip()

            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in "\"'"
            ):
                value = value[1:-1]

            if (
                value.startswith("[")
                and value.endswith("]")
            ):
                value = [
                    item.strip().strip(
                        "\"'"
                    )
                    for item in value[1:-1].split(
                        ","
                    )
                    if item.strip()
                ]

            elif value.lower() == "true":
                value = True

            elif value.lower() == "false":
                value = False

            data[key] = value

        return (
            data,
            "\n".join(
                lines[end + 1:]
            )
        )

    def splitSections(self, body):
        matches = list(
            re.finditer(
                r"^##\s+(.+?)\s*$",
                body,
                re.MULTILINE
            )
        )

        sections = {}

        for index, match in enumerate(matches):
            title = match.group(1).strip()

            start = match.end()

            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(body)
            )

            sections[
                title.lower()
            ] = body[start:end].strip()

        return sections

    def parseRules(self, body):
        sections = self.splitSections(
            body
        )

        ruleText = (
            sections.get("rules")
            or sections.get("rule")
        )

        if not ruleText:
            return []

        rules = []

        for line in ruleText.splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("<!--"):
                continue

            if line.startswith("#"):
                continue

            if (
                "→" in line
                or ">" in line
            ):
                rules.append(
                    Rule(line)
                )

        return rules

    def loadChanges(self):
        changes = []

        for path in self.changesDir.glob(
            "*.md"
        ):
            text = self.readMarkdown(
                path
            )

            metadata, body = (
                self.parseFrontmatter(
                    text
                )
            )

            changeId = str(
                metadata.get(
                    "id",
                    ""
                )
            ).strip()

            if not changeId:
                match = re.match(
                    r"(\d+)",
                    path.stem
                )

                if match:
                    changeId = (
                        match.group(1)
                    )

            if not changeId:
                continue

            rules = self.parseRules(
                body
            )

            if not rules:
                continue

            change = Change(
                changeId,
                str(
                    metadata.get(
                        "name",
                        path.stem
                    )
                ),
                str(
                    metadata.get(
                        "stage",
                        "Proto"
                    )
                ),
                path,
                rules
            )

            changes.append(change)

        changes.sort(
            key=lambda change: (
                change.order,
                change.id
            )
        )

        return changes

    def loadLexicon(self):
        entries = []

        for path in self.lexiconDir.glob(
            "*.md"
        ):
            text = self.readMarkdown(
                path
            )

            metadata, body = (
                self.parseFrontmatter(
                    text
                )
            )

            proto = str(
                metadata.get(
                    "proto",
                    ""
                )
            ).strip()

            current = str(
                metadata.get(
                    "current",
                    proto
                )
            ).strip()

            if not proto:
                continue

            entries.append(
                Lexeme(
                    path,
                    metadata,
                    body,
                    proto,
                    current
                )
            )

        return entries

    def parseList(self, text):
        text = text.strip()

        if (
            text.startswith("(")
            and text.endswith(")")
        ):
            return [
                item.strip()
                for item in text[1:-1].split(
                    ","
                )
                if item.strip()
            ]

        return [text]

    def expandMappings(
        self,
        source,
        target
    ):
        sources = self.parseList(
            source
        )

        targets = self.parseList(
            target
        )

        if len(sources) == 1:
            return [
                (
                    sources[0],
                    targetValue
                )
                for targetValue in targets
            ]

        if len(targets) == 1:
            return [
                (
                    sourceValue,
                    targets[0]
                )
                for sourceValue in sources
            ]

        if len(sources) != len(targets):
            raise ValueError(
                "Parallel rule has different "
                f"list sizes: "
                f"{source} → {target}"
            )

        return list(
            zip(
                sources,
                targets
            )
        )

    def tokenize(self, text):
        text = text.strip()

        if not text:
            return []

        tokens = []
        index = 0

        while index < len(text):
            if text[index].isspace():
                index += 1
                continue

            if text[index] == "(":
                end = text.find(
                    ")",
                    index
                )

                if end == -1:
                    raise ValueError(
                        f"Unclosed list: "
                        f"{text}"
                    )

                tokens.append(
                    text[index:end + 1]
                )

                index = end + 1
                continue

            if text[index] == "$":
                match = re.match(
                    r"\$[A-Za-z]"
                    r"[A-Za-z0-9_]*",
                    text[index:]
                )

                if not match:
                    raise ValueError(
                        "Invalid class token: "
                        f"{text[index:]}"
                    )

                tokens.append(
                    match.group(0)
                )

                index += len(
                    match.group(0)
                )

                continue

            if text[index] == "#":
                tokens.append("#")
                index += 1
                continue

            if text[index] == "@":
                tokens.append("@")
                index += 1
                continue

            tokens.append(
                text[index]
            )

            index += 1

        return tokens

    def expandContextToken(
        self,
        token
    ):
        if token == "":
            return [""]

        if token == "@":
            return ["@"]

        if (
            token.startswith("(")
            and token.endswith(")")
        ):
            return [
                item.strip()
                for item in token[1:-1].split(
                    ","
                )
                if item.strip()
            ]

        if token.startswith("$"):
            return self.phonology.get(
                token
            ).phonemes

        return [token]

    def matchLeft(
        self,
        form,
        cursor,
        tokens
    ):
        for token in reversed(tokens):
            if token == "#":
                if cursor != 0:
                    return False

                continue

            options = (
                self.expandContextToken(
                    token
                )
            )

            matched = False

            for option in options:
                if option == "@":
                    matched = True
                    break

                length = len(option)

                if (
                    cursor >= length
                    and form[
                        cursor - length:
                        cursor
                    ] == option
                ):
                    cursor -= length
                    matched = True
                    break

            if not matched:
                return False

        return True

    def matchRight(
        self,
        form,
        cursor,
        tokens
    ):
        for token in tokens:
            if token == "#":
                if cursor != len(form):
                    return False

                continue

            options = (
                self.expandContextToken(
                    token
                )
            )

            matched = False

            for option in options:
                if option == "@":
                    matched = True
                    break

                if form[
                    cursor:
                    cursor + len(option)
                ] == option:
                    cursor += len(option)
                    matched = True
                    break

            if not matched:
                return False

        return True

    def matchesContext(
        self,
        form,
        start,
        end,
        leftContext,
        rightContext
    ):
        leftTokens = self.tokenize(
            leftContext
        )

        rightTokens = self.tokenize(
            rightContext
        )

        return (
            self.matchLeft(
                form,
                start,
                leftTokens
            )
            and self.matchRight(
                form,
                end,
                rightTokens
            )
        )

    def findMappings(
        self,
        form,
        mappings,
        leftContext,
        rightContext
    ):
        matches = []

        for source, target in mappings:
            sourceValue = (
                ""
                if source == "@"
                else source
            )

            if sourceValue == "":
                positions = range(
                    len(form) + 1
                )
            else:
                positions = [
                    match.start()
                    for match in re.finditer(
                        re.escape(
                            sourceValue
                        ),
                        form
                    )
                ]

            for start in positions:
                end = (
                    start
                    + len(sourceValue)
                )

                if not self.matchesContext(
                    form,
                    start,
                    end,
                    leftContext,
                    rightContext
                ):
                    continue

                replacement = (
                    ""
                    if target == "@"
                    else target
                )

                matches.append(
                    (
                        start,
                        end,
                        replacement
                    )
                )

        matches.sort(
            key=lambda item: (
                item[0],
                item[1]
            )
        )

        return matches

    def applyRule(
        self,
        form,
        rule
    ):
        mappings = (
            self.expandMappings(
                rule.source,
                rule.target
            )
        )

        matches = (
            self.findMappings(
                form,
                mappings,
                rule.leftContext,
                rule.rightContext
            )
        )

        if not matches:
            return form, False

        result = []
        cursor = 0

        for start, end, replacement in matches:
            if start < cursor:
                continue

            result.append(
                form[cursor:start]
            )

            result.append(
                replacement
            )

            cursor = end

        result.append(
            form[cursor:]
        )

        newForm = "".join(result)

        return (
            newForm,
            newForm != form
        )

    def applyChange(
        self,
        form,
        change
    ):
        current = form
        changed = False

        for rule in change.rules:
            current, ruleChanged = (
                self.applyRule(
                    current,
                    rule
                )
            )

            changed = (
                changed
                or ruleChanged
            )

        return current, changed

    def replaceCurrent(
        self,
        text,
        current
    ):
        if re.search(
            r"^current:\s*.*$",
            text,
            re.MULTILINE
        ):
            return re.sub(
                r"^current:\s*.*$",
                f"current: {current}",
                text,
                count=1,
                flags=re.MULTILINE
            )

        if text.startswith("---"):
            lines = text.splitlines()

            for index, line in enumerate(
                lines
            ):
                if (
                    line.strip() == "---"
                    and index > 0
                ):
                    lines.insert(
                        index,
                        f"current: {current}"
                    )

                    return "\n".join(
                        lines
                    )

        return text

    def updateHistory(
        self,
        text,
        history
    ):
        historySection = (
            "## History\n\n"
            "| Stage | Form | Change |\n"
            "| ----- | ---- | ------ |\n"
        )

        for stage, form, changeId in history:
            if changeId:
                change = f"[[{changeId}]]"
            else:
                change = ""

            historySection += (
                f"| {stage} | {form} "
                f"| {change} |\n"
            )

        if "## History" in text:
            text = text.split(
                "## History",
                1
            )[0].rstrip()

        return (
            text
            + "\n\n"
            + historySection
        )

    def processEntry(
        self,
        entry,
        changes,
        selectedStage=None
    ):
        text = self.readMarkdown(
            entry.path
        )

        current = entry.proto
        history = [
            (
                "Proto",
                current,
                ""
            )
        ]
        changesMade = []

        for change in changes:
            if (
                selectedStage is not None
                and change.stage != selectedStage
            ):
                continue

            newForm, changed = (
                self.applyChange(
                    current,
                    change
                )
            )

            if not changed:
                continue

            current = newForm

            history.append(
                (
                    change.stage,
                    current,
                    change.id
                )
            )

            changesMade.append(
                change.id
            )

        text = self.replaceCurrent(
            text,
            current
        )

        text = self.updateHistory(
            text,
            history
        )

        return (
            current,
            text,
            changesMade
        )

    def preview(
        self,
        entries,
        changes,
        selectedStage=None
    ):
        stages = {}

        for change in changes:
            stages.setdefault(
                change.stage,
                []
            ).append(change)

        for stage, stageChanges in stages.items():
            if (
                selectedStage is not None
                and stage != selectedStage
            ):
                continue

            print(
                f"=== {stage} ==="
            )
            print()

            for entry in entries:
                current = entry.proto

                meaning = (
                    entry.metadata.get(
                        "meaning",
                        ""
                    )
                )

                for change in stageChanges:
                    before = current

                    current, changed = (
                        self.applyChange(
                            current,
                            change
                        )
                    )

                    if changed:
                        print(
                            f"{entry.proto} "
                            f"[{meaning}]: "
                            f"{before} → {current} "
                            f"[[{change.id}]]"
                        )

            print()

    def apply(
        self,
        entries,
        changes,
        selectedStage=None
    ):
        changedFiles = []

        for entry in entries:
            current, text, changesMade = (
                self.processEntry(
                    entry,
                    changes,
                    selectedStage
                )
            )

            if changesMade:
                entry.path.write_text(
                    text,
                    encoding="utf-8"
                )

                changedFiles.append(
                    (
                        entry.path,
                        changesMade,
                        current
                    )
                )

        return changedFiles


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true"
    )

    parser.add_argument(
        "--stage"
    )

    parser.add_argument(
        "--list",
        action="store_true"
    )

    args = parser.parse_args()

    if not ROOT.exists():
        print(
            f"Project root not found: {ROOT}"
        )

        return 1

    try:
        engine = Engine(ROOT)
        changes = engine.loadChanges()
        entries = engine.loadLexicon()

    except (
        FileNotFoundError,
        ValueError
    ) as error:
        print(
            f"Error: {error}"
        )

        return 1

    if args.list:
        print("Phoneme classes:")
        print()

        for symbol in engine.phonology.symbols():
            phonemeClass = (
                engine.phonology.get(
                    symbol
                )
            )

            print(
                f"{symbol}  "
                f"{phonemeClass.name}: "
                f"{' '.join(phonemeClass.phonemes)}"
            )

        print()
        print("Changes:")
        print()

        for change in changes:
            print(
                f"{change.id}  "
                f"{change.stage}  "
                f"{change.name}  "
                f"({len(change.rules)} rules)"
            )

        return 0

    if not changes:
        print(
            "No changes found."
        )

        return 1

    if not entries:
        print(
            "No lexicon entries found."
        )

        return 1

    if args.apply:
        changedFiles = engine.apply(
            entries,
            changes,
            args.stage
        )

        print(
            f"Updated "
            f"{len(changedFiles)} "
            f"lexicon file(s)."
        )

        for path, changeIds, current in changedFiles:
            print(
                f"{path.name}: "
                f"{', '.join(changeIds)} "
                f"→ {current}"
            )

        return 0

    engine.preview(
        entries,
        changes,
        args.stage
    )

    print(
        "Dry run. Use --apply "
        "to write changes."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
