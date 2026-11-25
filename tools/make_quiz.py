"""Video savollari qoralamasini tayyorlaydi (admin tasdiqlashi kerak).
Savollar faqat video nomidagi mavzuga va umumiy ma'lumotga asoslanadi — video ichidagi tafsilotlarga emas.
Ishga tushirish: python tools/make_quiz.py  -> seed_data/quiz_drafts.json"""
import gzip
import json
import os
import random
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rnd = random.Random(7)


def Q(q, right, w1, w2=None):
    opts = [right, w1] + ([w2] if w2 else [])
    rnd.shuffle(opts)
    keys = "abc"
    return {"q": q, "a": opts[0], "b": opts[1], "c": opts[2] if len(opts) > 2 else None,
            "correct": keys[opts.index(right)]}


LETTER_WORDS = {
    "A": ("Anor", "Olma", "Uzum"), "B": ("Baliq", "Mushuk", "Ot"), "D": ("Daraxt", "Uy", "Qush"),
    "E": ("Eshik", "Olma", "Nok"), "F": ("Fil", "Sher", "It"), "G": ("Gul", "Non", "Suv"),
    "H": ("Havo", "Olma", "Kitob"), "I": ("Ilon", "Baliq", "Ot"), "J": ("Jo'ja", "Mushuk", "Qush"),
    "K": ("Kitob", "Daftar", "Ruchka"), "L": ("Lola", "Olma", "Nok"), "M": ("Mushuk", "It", "Ot"),
    "N": ("Non", "Suv", "Choy"), "O": ("Olma", "Nok", "Uzum"), "P": ("Paxta", "Gul", "Daraxt"),
    "Q": ("Qush", "Baliq", "Ot"), "R": ("Rasm", "Kitob", "Uy"), "S": ("Sut", "Non", "Choy"),
    "T": ("Tuxum", "Olma", "Non"), "U": ("Uzum", "Olma", "Nok"), "V": ("Velosiped", "Mashina", "Avtobus"),
    "X": ("Xo'roz", "Mushuk", "It"), "Y": ("Yulduz", "Oy", "Quyosh"), "Z": ("Zebra", "Fil", "Sher"),
    "O'": ("O'rdak", "Tovuq", "G'oz"), "G'": ("G'oz", "O'rdak", "Tovuq"), "Sh": ("Sher", "Fil", "Bo'ri"),
    "Ch": ("Choy", "Sut", "Suv"),
}


def letter_q(letter):
    right, w1, w2 = LETTER_WORDS[letter]
    # noto'g'ri variantlar shu harfdan boshlanmasin
    return [Q(f"Qaysi so'z «{letter}» harfi bilan boshlanadi?", right, w1 if not w1.startswith(letter) else "Uy",
              w2 if not w2.startswith(letter) else "Suv")]


EN = {"fruit": [("Olma", "Apple", "Banana", "Orange"), ("Banan", "Banana", "Apple", "Grape")],
      "veg": [("Sabzi", "Carrot", "Potato", "Tomato"), ("Pomidor", "Tomato", "Carrot", "Onion")],
      "pet": [("Mushuk", "Cat", "Dog", "Cow"), ("It", "Dog", "Cat", "Horse")],
      "wild": [("Sher", "Lion", "Tiger", "Bear"), ("Fil", "Elephant", "Monkey", "Lion")],
      "insect": [("Asalari", "Bee", "Ant", "Butterfly"), ("Kapalak", "Butterfly", "Bee", "Fly")],
      "sea": [("Baliq", "Fish", "Whale", "Crab"), ("Kit", "Whale", "Fish", "Shark")],
      "bird": [("Qush", "Bird", "Fish", "Cat"), ("Boyqush", "Owl", "Duck", "Eagle")],
      "food": [("Non", "Bread", "Milk", "Egg"), ("Sut", "Milk", "Bread", "Water")],
      "school": [("Kitob", "Book", "Pen", "Bag"), ("Ruchka", "Pen", "Book", "Ruler")],
      "transport": [("Avtobus", "Bus", "Car", "Train"), ("Samolyot", "Plane", "Ship", "Bus")],
      "clothes": [("Ko'ylak", "Shirt", "Hat", "Shoes"), ("Shapka", "Hat", "Shirt", "Coat")],
      "warm": [("Palto", "Coat", "Hat", "Shirt"), ("Sharf", "Scarf", "Coat", "Gloves")],
      "kitchen": [("Qoshiq", "Spoon", "Fork", "Cup"), ("Piyola", "Cup", "Plate", "Spoon")],
      "jobs": [("Shifokor", "Doctor", "Teacher", "Driver"), ("O'qituvchi", "Teacher", "Doctor", "Cook")],
      "house": [("Eshik", "Door", "Window", "Roof"), ("Deraza", "Window", "Door", "Wall")],
      "furniture": [("Stol", "Table", "Chair", "Bed"), ("Stul", "Chair", "Table", "Sofa")],
      "tech": [("Telefon", "Phone", "Computer", "TV"), ("Kompyuter", "Computer", "Phone", "Tablet")],
      "appliance": [("Muzlatgich", "Fridge", "Oven", "Kettle"), ("Choynak", "Kettle", "Fridge", "Iron")]}
RU = {"fruit": [("Olma", "Яблоко", "Груша", "Банан")], "veg": [("Sabzi", "Морковь", "Картофель", "Лук")],
      "pet": [("Mushuk", "Кошка", "Собака", "Корова")], "wild": [("Ayiq", "Медведь", "Волк", "Лиса")],
      "sea": [("Baliq", "Рыба", "Кит", "Краб")], "insect": [("Asalari", "Пчела", "Муравей", "Бабочка")],
      "bird": [("Qush", "Птица", "Рыба", "Кошка")], "food": [("Non", "Хлеб", "Молоко", "Яйцо")],
      "school": [("Kitob", "Книга", "Ручка", "Тетрадь")], "transport": [("Mashina", "Машина", "Автобус", "Поезд")],
      "clothes": [("Ko'ylak", "Рубашка", "Шапка", "Обувь")], "warm": [("Palto", "Пальто", "Шарф", "Шапка")],
      "kitchen": [("Qoshiq", "Ложка", "Вилка", "Чашка")], "jobs": [("Shifokor", "Врач", "Учитель", "Повар")],
      "house": [("Eshik", "Дверь", "Окно", "Крыша")], "furniture": [("Stol", "Стол", "Стул", "Кровать")],
      "tech": [("Telefon", "Телефон", "Компьютер", "Планшет")],
      "appliance": [("Muzlatgich", "Холодильник", "Плита", "Чайник")],
      "family": [("Ona", "Мама", "Папа", "Брат")], "body": [("Qo'l", "Рука", "Нога", "Голова")],
      "colors": [("Qizil", "Красный", "Синий", "Зелёный")], "shapes": [("Doira", "Круг", "Квадрат", "Треугольник")]}
TOPIC_WORDS = [("sabzavot", "veg"), ("meva", "fruit"), ("uy hayvon", "pet"), ("yovvoyi", "wild"),
               ("hasharot", "insect"), ("dengiz", "sea"), ("qush", "bird"), ("oziq", "food"),
               ("o‘quv qurol", "school"), ("maktab anjom", "school"), ("gadjet", "tech"), ("yengil kiyim", "clothes"),
               ("issiq kiyim", "warm"), ("uy texnika", "appliance"), ("maishiy", "appliance"),
               ("transport", "transport"), ("oshxona", "kitchen"), ("mebel", "furniture"), ("uy jihoz", "furniture"),
               ("kasb", "jobs"), ("uy qism", "house"), ("oila", "family"), ("tana", "body"), ("rang", "colors"),
               ("shakl", "shapes")]


def lang_q(title, low):
    lang = "ingliz" if "ingliz" in low else ("rus" if "rus" in low else None)
    if not lang:
        return []
    bank = EN if lang == "ingliz" else RU
    for key, topic in TOPIC_WORDS:
        if key in low and topic in bank:
            return [Q(f"«{uz}» {lang} tilida qanday bo'ladi?", r, w1, w2) for uz, r, w1, w2 in bank[topic][:2]]
    return []


# mavzu kalit so'zi -> savollar (umumiy bilim)
TOPICS = [
    (r"mevalar|kuzgi meva", [Q("Qaysi biri meva?", "Olma", "Sabzi", "Piyoz"),
                             Q("Qaysi meva sariq rangda?", "Banan", "Olcha", "Tarvuz ichi")]),
    (r"sabzavot", [Q("Qaysi biri sabzavot?", "Sabzi", "Olma", "Uzum")]),
    (r"hafta kun", [Q("Haftada necha kun bor?", "7", "5", "10"),
                    Q("Dushanbadan keyin qaysi kun keladi?", "Seshanba", "Juma", "Yakshanba")]),
    (r"shakl", [Q("Uchburchakning nechta burchagi bor?", "3", "4", "5"),
                Q("Qaysi shaklning burchagi yo'q?", "Doira", "Kvadrat", "Uchburchak")]),
    (r"yo'l harakat|yo'l qoida|yo‘l harakat", [Q("Svetoforning qaysi chirog'ida yo'ldan o'tamiz?", "Yashil", "Qizil", "Sariq"),
                                               Q("Yo'lni qayerdan kesib o'tamiz?", "Piyodalar o'tish joyidan", "Istalgan joydan", "Mashinalar orasidan")]),
    (r"toza qo'l|qo'l yuvish|gigiyena|top-toza", [Q("Ovqatdan oldin nima qilamiz?", "Qo'limizni yuvamiz", "Uxlaymiz", "Yuguramiz"),
                                                  Q("Qo'lni nima bilan yuvamiz?", "Sovun bilan", "Sut bilan", "Qum bilan")]),
    (r"badantarbiya", [Q("Badantarbiya nima uchun kerak?", "Sog'lom va baquvvat bo'lish uchun", "Uxlash uchun", "Shirinlik yeyish uchun")]),
    (r"suv|suvni asra", [Q("Suvni qanday asraymiz?", "Jo'mrakni o'z vaqtida yopamiz", "Jo'mrakni ochiq qoldiramiz", "Suvni yerga to'kamiz")]),
    (r"ekolog|tabiat|yashil makon|chiqindi|yelim xalta", [Q("Chiqindini qayerga tashlaymiz?", "Axlat qutisiga", "Ko'chaga", "Ariqqa"),
                                                           Q("Tabiatni qanday asraymiz?", "Daraxt ekamiz", "Gullarni yulamiz", "Axlat tashlaymiz")]),
    (r"kasb", [Q("Kasal bo'lganda kimga boramiz?", "Shifokorga", "Oshpazga", "Haydovchiga"),
               Q("Maktabda kim dars beradi?", "O'qituvchi", "Quruvchi", "Sotuvchi")]),
    (r"doktor", [Q("Shifokor nima qiladi?", "Kasallarni davolaydi", "Non yopadi", "Uy quradi")]),
    (r"koinot", [Q("Biz qaysi sayyorada yashaymiz?", "Yer", "Mars", "Oy"),
                 Q("Kunduzi osmonda nima porlaydi?", "Quyosh", "Oy", "Yulduzlar")]),
    (r"navro'z|navro‘z", [Q("Navro'z bayrami qachon nishonlanadi?", "21-mart", "1-iyun", "1-sentabr")]),
    (r"mustaqillik", [Q("O'zbekiston Mustaqillik kuni qachon?", "1-sentabr", "21-mart", "8-mart")]),
    (r"onajonlar|8 mart", [Q("Xotin-qizlar bayrami qachon nishonlanadi?", "8-mart", "1-iyun", "9-may")]),
    (r"bolalar kuni", [Q("Bolalarni himoya qilish kuni qachon?", "1-iyun", "1-sentabr", "8-mart")]),
    (r"ona tilim|21- oktabr", [Q("O'zbek tili bayrami qachon nishonlanadi?", "21-oktabr", "1-iyun", "21-mart")]),
    (r"maktab", [Q("Maktabga nima olib boramiz?", "Kitob va daftar", "Yostiq", "Kastryulka")]),
    (r"matematika", [Q("2 + 3 nechaga teng?", "5", "4", "6"), Q("5 dan keyin qaysi son keladi?", "6", "4", "7")]),
    (r"sana|sonlar|bir, ikki", [Q("3 ta olmaga yana 1 ta olma qo'shsak, nechta bo'ladi?", "4", "3", "5")]),
    (r"rang", [Q("Osmon qanday rangda?", "Ko'k", "Qizil", "Qora"), Q("Maysa qanday rangda?", "Yashil", "Sariq", "Binafsha")]),
    (r"hayvon", [Q("Sigir bizga nima beradi?", "Sut", "Asal", "Jun"), Q("Qaysi hayvon «miyov» deydi?", "Mushuk", "It", "Sigir")]),
    (r"qushlar ovozi", [Q("Qaysi qush kechasi uxlamaydi?", "Boyqush", "Kaptar", "Tovuq")]),
    (r"ob-havo", [Q("Yomg'ir yog'sa nima olamiz?", "Soyabon", "Quyosh ko'zoynak", "Chana")]),
    (r"kuz fasli", [Q("Kuzda daraxt barglari qanday bo'ladi?", "Sariq", "Ko'k", "Pushti")]),
    (r"non qayerdan", [Q("Non nimadan tayyorlanadi?", "Bug'doy unidan", "Sutdan", "Shakardan")]),
    (r"katta va kichkina|o'lcham|o'lchov", [Q("Qaysi biri katta?", "Fil", "Sichqon", "Chumoli")]),
    (r"sayohat", [Q("Qaysi transport osmonda uchadi?", "Samolyot", "Poyezd", "Kema")]),
    (r"maxsus mashina", [Q("Yong'inni kim o'chiradi?", "O't o'chiruvchilar", "Sotuvchilar", "Oshpazlar"),
                         Q("Tez yordam mashinasining telefon raqami?", "103", "101", "102")]),
    (r"kitob", [Q("Kitobni qanday asraymiz?", "Toza qo'l bilan ushlaymiz", "Yirtamiz", "Suvga tashlaymiz")]),
    (r"odob|rahmat|uzr|halollik", [Q("Biror narsa olganda nima deymiz?", "Rahmat", "Ket", "Bermayman"),
                                    Q("Xato qilsak nima qilamiz?", "Uzr so'raymiz", "Yashiramiz", "Yig'laymiz")]),
    (r"dangasa|erinchoq", [Q("Yaxshi bola qanday bo'ladi?", "Mehnatkash", "Dangasa", "Erinchoq")]),
    (r"alifbo", [Q("O'zbek alifbosi qaysi harf bilan boshlanadi?", "A", "B", "Z")]),
]

# Qur'onda nomi kelgan jonzotlar va boshqa islomiy qissalar (mashhur, umumiy ma'lum faktlar)
ISLAMIC_TITLE = [
    (r"qarg'a", Q("Bu qissada qaysi qush haqida so'z boradi?", "Qarg'a", "Kaptar", "Burgut")),
    (r"solih.*tuya", Q("Solih alayhissalomga mo'jiza qilib qaysi hayvon berilgan?", "Tuya", "Ot", "Fil")),
    (r"ibrohim alayhissalomning qushi", Q("Bu qissa qaysi payg'ambar haqida?", "Ibrohim alayhissalom", "Muso alayhissalom", "Nuh alayhissalom")),
    (r"yusuf.*bo'ri", Q("Yusuf alayhissalomning akalari otalariga qaysi hayvonni bahona qilishgan?", "Bo'ri", "Sher", "Ayiq")),
    (r"yunus.*kit", Q("Yunus alayhissalomni qaysi jonzot yutib yuborgan?", "Kit (katta baliq)", "Sher", "Fil")),
    (r"muso.*hassa", Q("Muso alayhissalomning hassasi nimaga aylangan?", "Ilonga", "Qushga", "Gulga")),
    (r"sigir", Q("Bu qissada qaysi hayvon haqida so'z boradi?", "Sigir", "Echki", "Tuya")),
    (r"chumoli", Q("Sulaymon alayhissalom qaysi jonzotning gapini eshitgan?", "Chumoli", "Baliq", "Fil")),
    (r"hudhud", Q("Hudhud qanday jonzot?", "Qush", "Baliq", "Hasharot")),
    (r"uzayr.*eshag", Q("Uzayr alayhissalomning qaysi hayvoni bo'lgan?", "Eshak", "Ot", "Tuya")),
    (r"kahf.*it", Q("As'hobul-Kahf bilan g'orda qaysi hayvon bo'lgan?", "It", "Mushuk", "Qo'y")),
    (r"loydan yaralgan qush", Q("Iso alayhissalom loydan nima yasagan?", "Qush", "Baliq", "Ot")),
    (r"abraha|fil voqeasi", Q("Abraha Ka'baga qaysi hayvon bilan kelgan?", "Fil", "Tuya", "Ot")),
    (r"o'rgimchak", Q("G'or og'ziga qaysi jonzot to'r to'qigan?", "O'rgimchak", "Chumoli", "Asalari")),
    (r"zamzam", Q("Makkadagi muborak quduq nomi nima?", "Zamzam", "Kavsar", "Salsabil")),
    (r"ka'ba|ka’ba", Q("Ka'bani qaysi payg'ambar o'g'li bilan qurgan?", "Ibrohim alayhissalom", "Nuh alayhissalom", "Muso alayhissalom")),
]
ISLAMIC_SERIES = {
    "Yunus alayhissalom qissasi": [Q("Yunus alayhissalom qaysi jonzotning qornida qolgan?", "Kit (katta baliq)", "Tuya", "Sher"),
                                   Q("Yunus alayhissalom qiyinchilikda nima qilgan?", "Allohga duo qilgan", "Uxlagan", "Yig'lab o'tirgan")],
    "Payg'ambarlar qissasi: Ibrohim": [Q("Ibrohim alayhissalomni olovga tashlashganda olov qanday bo'ldi?", "Salqin va salomat", "Juda issiq", "O'chmadi"),
                                       Q("Ibrohim alayhissalomning o'g'li kim?", "Ismoil alayhissalom", "Yusuf alayhissalom", "Muso alayhissalom")],
    "Imom al-Buxoriy": [Q("Imom Buxoriy qaysi shaharda tug'ilgan?", "Buxoro", "Samarqand", "Toshkent"),
                        Q("Imom Buxoriyning mashhur kitobi qanday nomlanadi?", "Sahihi Buxoriy", "Qobusnoma", "Boburnoma")],
    "Allohning habibi Muhammad (1-fasl)": [Q("Payg'ambarimiz Muhammad alayhissalom qaysi shaharda tug'ilganlar?", "Makka", "Madina", "Buxoro"),
                                           Q("Payg'ambarimizning onalari kim?", "Omina", "Xadicha", "Oysha")],
    "Allohning habibi Muhammad (2-fasl)": [Q("Payg'ambarimiz Makkadan qaysi shaharga hijrat qilganlar?", "Madina", "Damashq", "Bag'dod")],
    "Allohning habibi Muhammad (3-fasl)": [Q("Musulmonlarning muqaddas kitobi qanday nomlanadi?", "Qur'on", "Tavrot", "Zabur")],
    "Islom qissalari": [Q("Musulmonlar kuniga necha mahal namoz o'qiydi?", "5", "3", "7")],
    "Qur'onda kelgan insonlar qissasi": [Q("Qur'on qaysi tilda nozil bo'lgan?", "Arab", "Fors", "Turk")],
    "Tobeinlar hayotidan qissalar": [Q("Salomlashganda nima deymiz?", "Assalomu alaykum", "Xayr", "Rahmat")],
    "Qur'ondagi oyat-belgilar qissalari": [Q("Qur'onda nechta sura bor?", "114", "30", "99")],
    "Qur'onda zikri kelgan ajoyibotlar": [Q("Nuh alayhissalom to'fondan qutulish uchun nima yasagan?", "Kema", "Uy", "Ko'prik")],
    "Qur'onda zikri kelgan ayollar qissasi": [Q("Iso alayhissalomning onalari kim?", "Maryam", "Oysha", "Fotima")],
}
SKIP_SERIES = {"Pomidor Do'ppi"}  # nomidan mavzu aniq emas


def main():
    data = json.load(gzip.open(os.path.join(HERE, "seed_data", "content.json.gz"), "rt", encoding="utf-8"))["content"]
    out = []
    for r in data:
        if r["series"] in SKIP_SERIES:
            continue
        title, low = r["title"], r["title"].lower()
        qs = []
        m = re.search(r"alifbosi - (\S+) harfi", title)
        if m and m.group(1).replace("‘", "'") in LETTER_WORDS:
            qs = letter_q(m.group(1).replace("‘", "'"))
        if not qs:
            qs = lang_q(title, low)
        if not qs and r["kind"] == "islamic":
            qs = [q for pat, q in ISLAMIC_TITLE if re.search(pat, low)][:1]
        if not qs and r["kind"] in ("cartoon", "video"):
            for pat, items in TOPICS:
                if re.search(pat, low):
                    qs = items
                    break
        for q in qs:
            out.append({"series": r["series"], "title": title, **q})
    for s, qs in ISLAMIC_SERIES.items():
        for q in qs:
            out.append({"series": s, "title": None, **q})
    path = os.path.join(HERE, "seed_data", "quiz_drafts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(len(out), "ta savol;", len({o["title"] for o in out if o["title"]}), "ta videoga +",
          sum(1 for o in out if not o["title"]), "ta serial savoli")


if __name__ == "__main__":
    main()
