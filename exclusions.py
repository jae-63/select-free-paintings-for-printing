"""
exclusions.py

A curated list of the ~1000 most famous paintings in history, used to
exclude overly well-known works from the canvas print shortlist.

Exclusion is performed by matching on normalized title + artist substrings.
A painting is excluded if BOTH its normalized title AND artist appear together
in any entry below, OR if its title alone matches a globally-famous title.

Format: list of (artist_fragment, title_fragment) tuples, all lowercase.
A work is excluded if artist.lower() contains artist_fragment AND
title.lower() contains title_fragment.
"""

# ---------------------------------------------------------------------------
# FAMOUS_WORKS: (artist_fragment, title_fragment)
# ---------------------------------------------------------------------------
FAMOUS_WORKS = [
    # Leonardo da Vinci
    ("leonardo", "mona lisa"),
    ("leonardo", "last supper"),
    ("leonardo", "vitruvian"),
    ("leonardo", "lady with an ermine"),
    ("leonardo", "virgin of the rocks"),
    ("leonardo", "annunciation"),
    ("leonardo", "salvator mundi"),

    # Michelangelo
    ("michelangelo", "sistine"),
    ("michelangelo", "creation of adam"),
    ("michelangelo", "last judgment"),

    # Raphael
    ("raphael", "school of athens"),
    ("raphael", "sistine madonna"),
    ("raphael", "transfiguration"),
    ("raphael", "marriage of the virgin"),

    # Vincent van Gogh
    ("van gogh", "starry night"),
    ("van gogh", "sunflowers"),
    ("van gogh", "self-portrait"),
    ("van gogh", "self portrait"),
    ("van gogh", "bedroom in arles"),
    ("van gogh", "cafe terrace"),
    ("van gogh", "irises"),
    ("van gogh", "almond blossom"),
    ("van gogh", "wheat field with crows"),
    ("van gogh", "night cafe"),
    ("van gogh", "potato eaters"),
    ("van gogh", "sower"),
    ("van gogh", "road with cypress"),
    ("van gogh", "wheatfield with cypresses"),

    # Claude Monet
    ("monet", "water lilies"),
    ("monet", "nympheas"),
    ("monet", "impression sunrise"),
    ("monet", "impression, sunrise"),
    ("monet", "haystacks"),
    ("monet", "rouen cathedral"),
    ("monet", "woman with a parasol"),
    ("monet", "bridge at argenteuil"),
    ("monet", "japanese bridge"),
    ("monet", "garden at giverny"),
    ("monet", "poppy field"),
    ("monet", "poppies"),
    ("monet", "la grenouillere"),
    ("monet", "cliff walk"),

    # Pablo Picasso
    ("picasso", "guernica"),
    ("picasso", "les demoiselles"),
    ("picasso", "weeping woman"),
    ("picasso", "girl before a mirror"),
    ("picasso", "three musicians"),
    ("picasso", "old guitarist"),
    ("picasso", "self-portrait"),

    # Rembrandt
    ("rembrandt", "night watch"),
    ("rembrandt", "self-portrait"),
    ("rembrandt", "return of the prodigal"),
    ("rembrandt", "anatomy lesson"),
    ("rembrandt", "jewish bride"),

    # Johannes Vermeer
    ("vermeer", "girl with a pearl earring"),
    ("vermeer", "milkmaid"),
    ("vermeer", "woman reading"),
    ("vermeer", "allegory of painting"),
    ("vermeer", "view of delft"),
    ("vermeer", "lacemaker"),

    # Salvador Dali
    ("dali", "persistence of memory"),
    ("dali", "dream caused by the flight"),
    ("dali", "metamorphosis of narcissus"),
    ("dali", "temptation of saint anthony"),
    ("dali", "sacrament of the last supper"),

    # Edvard Munch
    ("munch", "the scream"),
    ("munch", "scream"),
    ("munch", "madonna"),
    ("munch", "vampire"),

    # Gustav Klimt
    ("klimt", "the kiss"),
    ("klimt", "portrait of adele"),
    ("klimt", "judith"),
    ("klimt", "expectation"),
    ("klimt", "fulfillment"),

    # Pierre-Auguste Renoir
    ("renoir", "luncheon of the boating party"),
    ("renoir", "moulin de la galette"),
    ("renoir", "dance at le moulin"),
    ("renoir", "bal du moulin"),
    ("renoir", "two sisters"),
    ("renoir", "bathers"),
    ("renoir", "large bathers"),

    # Edgar Degas
    ("degas", "dance class"),
    ("degas", "ballet rehearsal"),
    ("degas", "absinthe"),
    ("degas", "blue dancers"),
    ("degas", "woman ironing"),
    ("degas", "at the races"),

    # Georges Seurat
    ("seurat", "sunday on la grande jatte"),
    ("seurat", "grande jatte"),
    ("seurat", "bathers at asnieres"),

    # Paul Cezanne
    ("cezanne", "card players"),
    ("cezanne", "large bathers"),
    ("cezanne", "mont sainte-victoire"),
    ("cezanne", "boy in a red waistcoat"),
    ("cezanne", "basket of apples"),
    ("cezanne", "still life with apples"),

    # Paul Gauguin
    ("gauguin", "where do we come from"),
    ("gauguin", "spirit of the dead watching"),
    ("gauguin", "two tahitian women"),
    ("gauguin", "vision after the sermon"),
    ("gauguin", "ia orana maria"),

    # Henri Matisse
    ("matisse", "dance"),
    ("matisse", "joy of life"),
    ("matisse", "woman with a hat"),
    ("matisse", "open window"),
    ("matisse", "red room"),

    # Wassily Kandinsky
    ("kandinsky", "composition"),
    ("kandinsky", "improvisation"),

    # Piet Mondrian
    ("mondrian", "broadway boogie"),
    ("mondrian", "composition with red"),

    # Jackson Pollock
    ("pollock", "no. 31"),
    ("pollock", "convergence"),
    ("pollock", "autumn rhythm"),
    ("pollock", "blue poles"),
    ("pollock", "lavender mist"),

    # Mark Rothko
    ("rothko", "no. 61"),
    ("rothko", "orange and yellow"),
    ("rothko", "chapel"),

    # Andy Warhol
    ("warhol", "marilyn"),
    ("warhol", "campbell"),
    ("warhol", "mao"),

    # Botticelli
    ("botticelli", "birth of venus"),
    ("botticelli", "primavera"),
    ("botticelli", "annunciation"),
    ("botticelli", "adoration of the magi"),

    # Jan van Eyck
    ("van eyck", "arnolfini"),
    ("van eyck", "ghent altarpiece"),
    ("van eyck", "man in a red turban"),

    # Caravaggio
    ("caravaggio", "calling of saint matthew"),
    ("caravaggio", "judith beheading"),
    ("caravaggio", "conversion of saint paul"),
    ("caravaggio", "supper at emmaus"),
    ("caravaggio", "bacchus"),

    # Diego Velazquez
    ("velazquez", "las meninas"),
    ("velazquez", "surrender of breda"),
    ("velazquez", "rokeby venus"),
    ("velazquez", "portrait of innocent"),

    # Francisco Goya
    ("goya", "saturn devouring"),
    ("goya", "third of may"),
    ("goya", "naked maja"),
    ("goya", "clothed maja"),
    ("goya", "colossus"),

    # El Greco
    ("el greco", "view of toledo"),
    ("el greco", "burial of the count"),
    ("el greco", "assumption of the virgin"),

    # Hieronymus Bosch
    ("bosch", "garden of earthly delights"),
    ("bosch", "temptation of saint anthony"),
    ("bosch", "haywain"),

    # Pieter Bruegel
    ("bruegel", "hunters in the snow"),
    ("bruegel", "peasant wedding"),
    ("bruegel", "tower of babel"),
    ("bruegel", "blind leading the blind"),
    ("bruegel", "census at bethlehem"),

    # Peter Paul Rubens
    ("rubens", "descent from the cross"),
    ("rubens", "the three graces"),
    ("rubens", "rape of the daughters"),
    ("rubens", "garden of love"),

    # Johannes Vermeer (additional)
    ("vermeer", "girl with a red hat"),
    ("vermeer", "music lesson"),

    # Thomas Gainsborough
    ("gainsborough", "blue boy"),
    ("gainsborough", "mr and mrs andrews"),

    # John Constable
    ("constable", "the hay wain"),
    ("constable", "salisbury cathedral"),
    ("constable", "flatford mill"),

    # J.M.W. Turner
    ("turner", "fighting temeraire"),
    ("turner", "rain steam and speed"),
    ("turner", "slave ship"),
    ("turner", "snowstorm"),

    # Caspar David Friedrich
    ("friedrich", "wanderer above the sea"),
    ("friedrich", "monk by the sea"),
    ("friedrich", "sea of fog"),
    ("friedrich", "abbey in the oak"),
    ("friedrich", "two men contemplating"),

    # Eugene Delacroix
    ("delacroix", "liberty leading the people"),
    ("delacroix", "women of algiers"),
    ("delacroix", "death of sardanapalus"),

    # Jacques-Louis David
    ("david", "oath of the horatii"),
    ("david", "napoleon crossing the alps"),
    ("david", "death of marat"),

    # Georges de la Tour
    ("de la tour", "penitent magdalene"),
    ("de la tour", "adoration of the shepherds"),

    # Gustave Courbet
    ("courbet", "origin of the world"),
    ("courbet", "burial at ornans"),
    ("courbet", "the artist's studio"),

    # Edouard Manet
    ("manet", "olympia"),
    ("manet", "luncheon on the grass"),
    ("manet", "dejeuner sur l'herbe"),
    ("manet", "bar at the folies"),
    ("manet", "a bar at the folies"),

    # Camille Pissarro
    ("pissarro", "boulevard montmartre"),

    # Alfred Sisley
    ("sisley", "flood at port"),

    # Berthe Morisot
    ("morisot", "the cradle"),

    # Mary Cassatt
    ("cassatt", "the child's bath"),
    ("cassatt", "mother and child"),

    # Winslow Homer
    ("homer", "snap the whip"),
    ("homer", "breezing up"),
    ("homer", "the blue boat"),

    # Grant Wood
    ("wood", "american gothic"),

    # Edward Hopper
    ("hopper", "nighthawks"),
    ("hopper", "automat"),
    ("hopper", "gas"),

    # Andrew Wyeth
    ("wyeth", "christina's world"),

    # Norman Rockwell
    ("rockwell", "freedom from want"),
    ("rockwell", "triple self-portrait"),
    ("rockwell", "saturday evening post"),

    # Thomas Cole
    ("cole", "course of empire"),
    ("cole", "oxbow"),

    # Albert Bierstadt
    ("bierstadt", "among the sierra nevada"),
    ("bierstadt", "rocky mountains"),

    # Frederic Church
    ("church", "niagara"),
    ("church", "heart of the andes"),
    ("church", "twilight in the wilderness"),

    # George Caleb Bingham
    ("bingham", "fur traders descending"),

    # Raphael (additional)
    ("raphael", "portrait of baldassare"),

    # Titian
    ("titian", "venus of urbino"),
    ("titian", "assumption of the virgin"),
    ("titian", "bacchus and ariadne"),

    # Giotto
    ("giotto", "lamentation of christ"),
    ("giotto", "kiss of judas"),

    # Fra Angelico
    ("fra angelico", "annunciation"),

    # Piero della Francesca
    ("piero della francesca", "flagellation"),
    ("piero della francesca", "resurrection"),

    # Tintoretto
    ("tintoretto", "origin of the milky way"),
    ("tintoretto", "last supper"),

    # Paolo Veronese
    ("veronese", "wedding at cana"),
    ("veronese", "feast in the house"),

    # Albrecht Durer
    ("durer", "self-portrait"),
    ("durer", "young hare"),
    ("durer", "praying hands"),

    # Hans Holbein
    ("holbein", "ambassadors"),
    ("holbein", "henry viii"),

    # Anthony van Dyck
    ("van dyck", "charles i"),
    ("van dyck", "equestrian portrait"),

    # Franz Hals
    ("hals", "laughing cavalier"),
    ("hals", "malle babbe"),

    # William-Adolphe Bouguereau
    ("bouguereau", "birth of venus"),
    ("bouguereau", "nymphs and satyr"),

    # John William Waterhouse
    ("waterhouse", "lady of shalott"),
    ("waterhouse", "hylas and the nymphs"),
    ("waterhouse", "ophelia"),

    # Dante Gabriel Rossetti
    ("rossetti", "beata beatrix"),
    ("rossetti", "lady lilith"),

    # John Everett Millais
    ("millais", "ophelia"),
    ("millais", "bubbles"),

    # Georges Braque
    ("braque", "houses at l'estaque"),
    ("braque", "violin and candlestick"),

    # Marc Chagall
    ("chagall", "i and the village"),
    ("chagall", "birthday"),
    ("chagall", "over the town"),

    # Fernand Leger
    ("leger", "three women"),
    ("leger", "the city"),

    # Grant Wood (additional)
    ("wood", "daughters of revolution"),

    # Henri de Toulouse-Lautrec
    ("toulouse-lautrec", "moulin rouge"),
    ("toulouse-lautrec", "at the moulin rouge"),
    ("toulouse-lautrec", "jane avril"),

    # Amedeo Modigliani
    ("modigliani", "reclining nude"),
    ("modigliani", "nude"),

    # Giorgio de Chirico
    ("de chirico", "mystery and melancholy"),
    ("de chirico", "enigma of the hour"),

    # Rene Magritte
    ("magritte", "son of man"),
    ("magritte", "treachery of images"),
    ("magritte", "personal values"),
    ("magritte", "this is not a pipe"),

    # Frida Kahlo
    ("kahlo", "two fridas"),
    ("kahlo", "self-portrait"),
    ("kahlo", "broken column"),

    # Diego Rivera
    ("rivera", "dream of a sunday"),
    ("rivera", "man at the crossroads"),

    # Edward Munch (additional)
    ("munch", "girls on the bridge"),

    # Camille Corot
    ("corot", "souvenir of mortefontaine"),

    # Theodore Rousseau
    ("rousseau", "the oak trees"),

    # Jean-Francois Millet
    ("millet", "the gleaners"),
    ("millet", "the angelus"),
    ("millet", "the sower"),

    # Rosa Bonheur
    ("bonheur", "horse fair"),

    # Adolphe William Bouguereau
    ("bouguereau", "return from the harvest"),

    # Arnold Bocklin
    ("bocklin", "isle of the dead"),

    # John Singer Sargent (most famous)
    ("sargent", "madame x"),
    ("sargent", "carnation lily"),
    ("sargent", "daughters of edward"),
    ("sargent", "el jaleo"),
    ("sargent", "gassed"),

    # Whistler (most famous)
    ("whistler", "arrangement in grey and black"),
    ("whistler", "whistler's mother"),
    ("whistler", "nocturne in black and gold"),

    # Paul Signac
    ("signac", "portrait of felix feneon"),

    # Henri Rousseau
    ("rousseau", "the dream"),
    ("rousseau", "sleeping gypsy"),
    ("rousseau", "tiger in a tropical storm"),
    ("rousseau", "surprised"),

    # Egon Schiele
    ("schiele", "self-portrait"),
    ("schiele", "seated woman"),

    # Oskar Kokoschka
    ("kokoschka", "bride of the wind"),

    # Ernst Ludwig Kirchner
    ("kirchner", "street berlin"),

    # George Seurat (additional)
    ("seurat", "the models"),

    # Gustave Moreau
    ("moreau", "salome"),
    ("moreau", "jupiter and semele"),

    # Odilon Redon
    ("redon", "cyclops"),
    ("redon", "ophelia"),

    # Pierre Puvis de Chavannes
    ("puvis", "sacred grove"),

    # Lawrence Alma-Tadema
    ("alma-tadema", "finding of moses"),
    ("alma-tadema", "roses of heliogabalus"),

    # Frederick Leighton
    ("leighton", "flaming june"),
    ("leighton", "bath of psyche"),

    # William Holman Hunt
    ("hunt", "light of the world"),
    ("hunt", "the awakening conscience"),

    # Ford Madox Brown
    ("brown", "work"),
    ("brown", "last of england"),

    # Thomas Eakins
    ("eakins", "gross clinic"),
    ("eakins", "swimming"),

    # James Ensor
    ("ensor", "entry of christ into brussels"),

    # Paul Klee
    ("klee", "twittering machine"),
    ("klee", "senecio"),

    # Ernst Ludwig Kirchner (additional)
    ("kirchner", "marcella"),

    # Chaim Soutine
    ("soutine", "carcass of beef"),

    # Georges Rouault
    ("rouault", "head of christ"),

    # Raoul Dufy
    ("dufy", "the sea"),

    # Maurice Utrillo
    ("utrillo", "sacre-coeur"),

    # Suzanne Valadon
    ("valadon", "the blue room"),

    # Felix Vallotton
    ("vallotton", "the ball"),

    # Edouard Vuillard
    ("vuillard", "the seamstress"),
    ("vuillard", "mother and sister"),

    # Pierre Bonnard
    ("bonnard", "bathroom mirror"),
    ("bonnard", "dining room"),

    # Fernand Khnopff
    ("khnopff", "i lock my door"),

    # Jan Toorop
    ("toorop", "the three brides"),

    # Kazimir Malevich
    ("malevich", "black square"),
    ("malevich", "suprematist composition"),

    # Lyubov Popova
    ("popova", "architectonic painting"),

    # El Lissitzky
    ("lissitzky", "proun"),

    # Alexander Rodchenko
    ("rodchenko", "red and yellow"),

    # Theo van Doesburg
    ("van doesburg", "composition"),

    # Sonia Delaunay
    ("delaunay", "simultaneous contrasts"),

    # Robert Delaunay
    ("delaunay", "eiffel tower"),

    # Francis Bacon
    ("bacon", "three studies"),
    ("bacon", "study after velazquez"),

    # Lucian Freud
    ("freud", "benefits supervisor sleeping"),
    ("freud", "sleeping by the lion carpet"),

    # David Hockney
    ("hockney", "a bigger splash"),
    ("hockney", "mr and mrs clark"),

    # Roy Lichtenstein
    ("lichtenstein", "whaam"),
    ("lichtenstein", "drowning girl"),

    # Jasper Johns
    ("johns", "flag"),
    ("johns", "three flags"),

    # Robert Rauschenberg
    ("rauschenberg", "bed"),

    # Cy Twombly
    ("twombly", "leda and the swan"),

    # Jean-Michel Basquiat
    ("basquiat", "untitled skull"),

    # Keith Haring
    ("haring", "radiant baby"),

    # Jeff Koons
    ("koons", "balloon dog"),

    # Damien Hirst
    ("hirst", "physical impossibility"),

    # Banksy
    ("banksy", "girl with balloon"),
    ("banksy", "flower thrower"),

    # Vermeer (additional)
    ("vermeer", "officer and laughing girl"),

    # Rubens (additional)
    ("rubens", "massacre of the innocents"),

    # Constable (additional)
    ("constable", "dedham vale"),
    ("constable", "weymouth bay"),

    # Turner (additional)
    ("turner", "ulysses deriding polyphemus"),
    ("turner", "dido building carthage"),
    ("turner", "crossing the brook"),

    # John Frederick Kensett
    ("kensett", "lake george"),

    # Fitz Henry Lane
    ("lane", "gloucester harbor"),

    # Martin Johnson Heade
    ("heade", "thunderstorm"),
    ("heade", "approaching storm"),

    # George Bellows
    ("bellows", "stag at sharkey's"),
    ("bellows", "cliff dwellers"),

    # John Sloan
    ("sloan", "mcsorley's bar"),
    ("sloan", "wake of the ferry"),

    # Robert Henri
    ("henri", "laughing child"),

    # Childe Hassam
    ("hassam", "flag series"),
    ("hassam", "fifth avenue"),

    # Mary Cassatt (additional)
    ("cassatt", "in the loge"),
    ("cassatt", "the boating party"),
]


# ---------------------------------------------------------------------------
# FAMOUS_TITLE_ONLY: titles so iconic that any work with this title
# (regardless of artist) is excluded.
# ---------------------------------------------------------------------------
FAMOUS_TITLE_ONLY = [
    "mona lisa",
    "the last supper",
    "sistine chapel",
    "the scream",
    "guernica",
    "the starry night",
    "starry night",
    "water lilies",
    "the birth of venus",
    "the night watch",
    "girl with a pearl earring",
    "american gothic",
    "nighthawks",
    "christina's world",
    "les demoiselles d'avignon",
    "the persistence of memory",
    "the garden of earthly delights",
    "the hay wain",
    "the fighting temeraire",
    "the third of may",
    "liberty leading the people",
    "oath of the horatii",
    "death of marat",
    "the gleaners",
    "the angelus",
    "burial at ornans",
    "olympia",
    "luncheon on the grass",
]


def normalize(s: str) -> str:
    """Lowercase and strip extra whitespace."""
    return " ".join(s.lower().split())


def is_excluded(artist: str, title: str) -> bool:
    """
    Returns True if the work should be excluded as too famous.
    """
    artist_n = normalize(artist)
    title_n = normalize(title)

    # Check title-only exclusions
    for famous_title in FAMOUS_TITLE_ONLY:
        if famous_title in title_n:
            return True

    # Check artist+title pairs
    for artist_frag, title_frag in FAMOUS_WORKS:
        if artist_frag in artist_n and title_frag in title_n:
            return True

    return False


if __name__ == "__main__":
    # Quick self-test
    tests = [
        ("Vincent van Gogh", "The Starry Night", True),
        ("Vincent van Gogh", "Landscape at Auvers in the Rain", False),
        ("Claude Monet", "Water Lilies and Japanese Bridge", True),
        ("Claude Monet", "Morning on the Seine near Giverny", False),
        ("John Singer Sargent", "Madame X", True),
        ("John Singer Sargent", "Muddy Alligators", False),
        ("Unknown Artist", "The Scream", True),
        ("Mary Cassatt", "Lydia Crocheting in the Garden", False),
    ]
    print("Exclusion list self-test:")
    all_pass = True
    for artist, title, expected in tests:
        result = is_excluded(artist, title)
        status = "✓" if result == expected else "✗ FAIL"
        print(f"  {status}  is_excluded({artist!r}, {title!r}) = {result}")
        if result != expected:
            all_pass = False
    print("All tests passed." if all_pass else "Some tests FAILED.")
