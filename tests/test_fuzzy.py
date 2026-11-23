"""Forgiving search (src/loft/fuzzy.py): words matched with slack, books ranked."""
from loft.fuzzy import Index, normalize, word_score


def test_normalize():
    assert normalize("Assassin’s Creed: Odyssey") == "assassins creed odyssey"
    assert normalize("Spider-Man  Öst") == "spider man ost"


def test_word_scores():
    assert word_score("wedding", "wedding") == 1.0
    assert word_score("nig", "night") == 0.9
    assert word_score("crash", "crashers") == 0.9 and word_score("rasher", "crashers") == 0.75
    assert word_score("weding", "wedding") == 0.7          # one missing letter
    assert word_score("wdeding", "wedding") == 0.7         # one swap (7 letters: 1 allowed)
    assert word_score("asassinss", "assassins") == 0.7     # two, in a long word
    assert word_score("cat", "cot") == 0.0                 # too short for a typo
    assert word_score("or", "okafor") == 0.0               # too short to match inside a word


def book(i, title, **kw):
    return {"id": i, "title": title, "series": kw.get("series", ""), "authors": kw.get("authors", []),
            "tags": kw.get("tags", []), "description": kw.get("description", ""), "sort_title": title.lower()}


def test_rank():
    ix = Index([book(1, "Wedding Crashers", authors=["Geronimo Stilton"], description="A mouse at a wedding"),
                book(2, "Spider-Man: Blue"), book(3, "Assassin's Creed: Odyssey"),
                book(4, "Mouse Island", description="no weddings here")])
    assert ix.rank("weding crashers", 10)[0] == 1
    assert ix.rank("geronimo stilton wedding book", 10)[0] == 1
    assert ix.rank("crashers geronimo mouse", 10)[0] == 1
    assert ix.rank("spiderman", 10) == [2] and ix.rank("spider man", 10)[0] == 2
    assert ix.rank("assassins creed", 10) == [3]
    assert ix.rank("mouse", 10) == [4, 1]                  # in the title beats in the description
    assert ix.rank("the", 10) == []                        # no book here has "the" as a word
    assert ix.rank("zzzz", 10) == []


def test_a_big_library_is_quick():
    import random, string, time
    rnd = random.Random(1)
    w = lambda: "".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(3, 10)))
    books = [book(i, " ".join(w() for _ in range(4)), authors=[w() + " " + w()],
                  description=" ".join(w() for _ in range(60))) for i in range(20000)]
    ix = Index(books)
    start = time.perf_counter()
    ix.rank("quick brwn foxes jumped", 40)
    took = time.perf_counter() - start
    print(f"search over 20000 books: {took * 1000:.0f} ms")
    assert took < 3.0   # about 0.5 s on a desktop PC, 1.3 s on GitHub's runners: this catches a search gone slow


# ---------- found in review: ranking and limits ----------

def test_an_extra_common_word_doesnt_bury_the_book():
    decoys = [book(10 + i, f"Assassin's Creed: Part {i}", description="the brotherhood returns in this graphic novel")
              for i in range(6)]
    ix = Index([book(1, "Assassin's Creed: Brotherhood")] + decoys)
    assert ix.rank("assassins creed brotherhood graphic novel", 10)[0] == 1
    ix = Index([book(1, "Harry Potter and the Goblet of Fire"),
                book(2, "Pottery for Beginners", description="A book about harrying clay")])
    assert ix.rank("harry potter book", 10)[0] == 1


def test_an_exact_author_beats_part_of_a_title_word():
    ix = Index([book(1, "Making Friends"), book(2, "Viking Saga"), book(3, "It", authors=["Stephen King"])])
    assert ix.rank("king", 10)[0] == 3


def test_joined_words_match_only_as_whole_words():
    ix = Index([book(1, "Blithe Rover"), book(2, "Quiet Days", description="her garden")])
    assert ix.rank("her", 10) == [2]          # not "blitherover"
    assert ix.rank("blitherover", 10) == [1]  # joined, the whole thing still counts


def test_matches_agree_with_word_score():
    ix = Index([book(1, "Entertainment Tonight")])
    for typed in ("ent", "enter", "tain", "entertainmnet", "tonite", "tonight"):
        found = ix._matches(typed)
        for i, w in enumerate(ix.vocab):
            if w not in ("entertainmenttonight",):
                assert found.get(i, 0.0) == word_score(typed, w), (typed, w)


def test_a_long_query_is_cut_short():
    ix = Index([book(1, "Zebra")])
    filler = " ".join(f"qq{i}x" for i in range(20))
    assert ix.rank(filler + " zebra", 10) == []        # only the first words count
    assert ix.rank("zebra " + filler, 10) == [1]
    assert ix.rank("x" * 5000, 10) == []                 # and only so many letters


def test_words_naming_the_book_count_more_than_its_tags():
    ix = Index([book(1, "Mein Kampf"), book(2, "Forsaken", tags=["Comics", "Graphic Novels"])])
    assert ix.rank("mein kampf graphic novel", 10)[0] == 1
    ix = Index([book(1, "Assassin's Creed: Brotherhood"),
                book(2, "Assassin's Creed: Brahman", tags=["Comic Book"], description="the Brotherhood")])
    assert ix.rank("assassins creed brotherhood book", 10)[0] == 1


def test_rare_words_count_more_than_common_ones():
    comics = [book(10 + i, f"Comic {i}", tags=["Graphic Novels"]) for i in range(10)]
    ix = Index([book(1, "Rumble in the Jungle"), book(2, "Aardvark Tales (Graphic Novel)")] + comics)
    assert ix.rank("rumble in the jungle graphic novel", 10)[0] == 1
    assert ix.rank("1984 graphic novel", 10)[0] == 2      # no "1984" here: the graphic novel is the best there is
