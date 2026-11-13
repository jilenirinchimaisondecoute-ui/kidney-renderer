import asyncio
from pathlib import Path

import edge_tts

TEXT = ("القصور الكلوي الحاد معناه إن الكلاوي توا ما عادت تصفّي الدم مليح، "
        "من أسبابه الجفاف الشديد، وإذا لقيت البول قلّ، ولا رجليك ورموا، روح للدكتور في نفس اليوم.")
OUT = Path("samples")


async def main():
    OUT.mkdir(exist_ok=True)
    voices = await edge_tts.list_voices()
    male = sorted(v["ShortName"] for v in voices
                  if v["Locale"].startswith("ar-") and v["Gender"] == "Male")
    done = []
    for name in male:
        try:
            await edge_tts.Communicate(TEXT, name).save(str(OUT / f"{name}.mp3"))
            done.append(name)
        except Exception as e:
            print("failed", name, e)
    Path("notes.txt").write_text("Male Arabic voices:\n" + "\n".join(done))
    print(done)


asyncio.run(main())
