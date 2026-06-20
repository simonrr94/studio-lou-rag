import os
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_embedding(text):
    response = openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def setup_index():
    index_name = os.getenv("PINECONE_INDEX_NAME")
    existing = [i.name for i in pc.list_indexes()]
    if index_name not in existing:
        print(f"Creating index '{index_name}'...")
        pc.create_index(
            name=index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        print("Index created.")
    else:
        print(f"Index '{index_name}' already exists.")
    return pc.Index(index_name)

def index_chunks(index, chunks):
    print(f"Embedding and indexing {len(chunks)} chunks...")
    vectors = []
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}/{len(chunks)}: {chunk['id']}")
        embedding = get_embedding(chunk["text"])
        vectors.append({
            "id": chunk["id"],
            "values": embedding,
            "metadata": {
                "text": chunk["text"],
                "category": chunk["category"]
            }
        })
    index.upsert(vectors=vectors)
    print(f"Done! {len(vectors)} chunks indexed.")

CHUNKS = [
    {"id": "brand-1", "category": "brand", "text": "Studio Lou is an interior design and growth marketing consultancy founded and run solely by Lauren. Phoenix-based, fully virtual practice. Lauren has 10 plus years of experience including stints at West Elm, Visual Comfort, Havenly, and boutique design firms. She holds degrees in both marketing and interior design. Studio Lou serves two primary audiences: homeowners seeking e-design services, and interior design firms seeking marketing strategy. The business also functions as a hidden portfolio for hiring managers at home and lifestyle DTC brands but this audience is never addressed directly in content."},
    {"id": "brand-2", "category": "brand", "text": "The Studio Lou voice brief: biased, opinionated, professional advice to a friend. Not generic. Not listicle. Warmer than the Wall Street Journal, sharper than a Pinterest caption. The wedge over competing content is that Lauren has actually done the thing she is writing about. Take positions."},
    {"id": "brand-3", "category": "brand", "text": "Studio Lou hard voice rules: No em dashes ever anywhere. No short staccato sentence strings. Do not default to the word curious in CTAs or closing lines. No performative humility. Do not describe the primary audience in third person in content directed at them. Never fabricate specific personal details. Do not repeat the same verb across nearby paragraphs. Never state a statistic without verifying it."},
    {"id": "brand-4", "category": "brand", "text": "Studio Lou voice person rules: Use we for general strategic claims and designer judgments. Use I for genuine personal disclosure such as Gavin, lived workspace experience, specific client observations. Use my clients not our clients when referring to Lauren's client relationships."},
    {"id": "brand-5", "category": "brand", "text": "Studio Lou visual brand system: papercraft and collage aesthetic. Primary palette: burgundy, linen warm off-white, sage green, slate. Typography: DM Sans Bold for headlines, Crimson Pro for editorial body, BiroScript Plus for handwritten accent. Carousel templates: Editorial Week 1, Data Insight Week 2, Comparison Week 3, List Week 4. Export 1080x1350 for LinkedIn, 1080x1080 for Instagram."},
    {"id": "brand-6", "category": "brand", "text": "Studio Lou tone by platform: Blog is professional advice to a friend, take positions, earned authority. LinkedIn is opinionated professional thought leadership, first-person credibility moments land well. Instagram is warmer and slightly more aspirational than LinkedIn, still opinionated not generic lifestyle. Pinterest is keyword-forward with credibility signal plus click hook. TikTok is most direct and personal, conversational, honest about what does and does not work."},
    {"id": "brand-7", "category": "brand", "text": "The Adapt-First Principle: before building anything from scratch, ask whether something already exists that can be adapted. Hierarchy: adapt existing content for a new platform first, extend or remix with a new angle second, build new from scratch only when neither serves the goal."},
    {"id": "ops-1", "category": "ops", "text": "Studio Lou four-month thematic arc: Month 1 AI x Interior Design, differentiator and highest-volume search topic. Month 2 Home Office Design, strongest performer, runs during heavy job-hunt period. Month 3 Marketing for Designers, hiring-manager bait, deployed when applications hit interview stage. Month 4 Startup and Modern Office Design, rounds out the year, bridges back to AI for SF startup audience."},
    {"id": "ops-2", "category": "ops", "text": "Studio Lou sprint week model: each month's full content output is produced in a single sprint week producing 3 to 4 full blog drafts, 4 hero carousels, 20 to 28 Pinterest pins, 4 TikTok slideshows, all captions for all platforms, and 1 to 2 TikTok reaction videos. Posting weeks that follow are kept light."},
    {"id": "ops-3", "category": "ops", "text": "Studio Lou posting cadence: LinkedIn 3 posts per week, Tuesday hero carousel, midweek text post, Friday single image or recap. Instagram 3 posts per week, Tuesday hero carousel, Thursday Reel or single image, Saturday lifestyle softener Week 1 or quick design tip Weeks 2 to 4. Pinterest 5 to 7 pins per week Monday through Saturday, no hashtags. TikTok 2 videos per week. Blog 1 hero post per week live Monday."},
    {"id": "ops-4", "category": "ops", "text": "Studio Lou scheduling tools: Buffer handles LinkedIn and TikTok, free tier 3 channels 10 posts per channel in queue. Meta Business Suite handles Instagram, free unlimited. Pinterest native scheduler used for Pinterest, free unlimited, native scheduling gets slightly better algorithmic reach."},
    {"id": "ops-5", "category": "ops", "text": "Studio Lou hashtag rules: Instagram has a hard five-hashtag cap enforced December 2025. Pinterest uses no hashtags, Pinterest stopped indexing them in 2022. LinkedIn performs best with three to five hashtags. Never use save this on LinkedIn."},
    {"id": "ops-6", "category": "ops", "text": "Studio Lou growth strategy: Pinterest is the strongest traffic driver. Reels are the only Instagram format reaching new audiences at current follower scale. Contrarian LinkedIn posts show the clearest engagement signal. TikTok reaction videos have higher organic reach potential than slideshows at small follower counts. The Zoom Backgrounds post is the strongest full-funnel asset."},
    {"id": "blog-1", "category": "blog", "text": "Every Studio Lou hero blog follows this skeleton in order: thumbnail summary, category label, H1 SEO-optimized, At a Glance table placed immediately after H1 before any prose, opening hook H2 250 to 300 words, H2 body sections in prose, conclusion H2 SEO-optimized not generic Final Thoughts, CTA either its own H3 formatted as Want Help Doing the Thing or folded into conclusion 120 to 150 words."},
    {"id": "blog-2", "category": "blog", "text": "The At a Glance table is a structural signature of every Studio Lou hero blog, NOT optional. Format: two-column table placed immediately after the H1, before any prose. Top row is a single At a Glance label spanning both columns, no other header row. Body cells contain ALL post H2 section titles flowing left-to-right then top-to-bottom in post order. This is NOT a Section Description table, NOT a comparison table, NOT a single-column list. Section titles only, two-column flow."},
    {"id": "blog-3", "category": "blog", "text": "Studio Lou blog word count targets: Opening hook approximately 250 to 300 words. Major body sections approximately 400 to 700 words each. Bridge sections approximately 300 to 400 words. Conclusion approximately 150 to 200 words. CTA approximately 120 to 150 words. Total hero post target 2400 to 2800 words. Blog drafting is always section by section, wait for sign-off before moving to the next section. Include word count at the end of each section."},
    {"id": "blog-4", "category": "blog", "text": "Studio Lou CTA standards: approximately 120 to 150 words. Conversational, slightly self-aware about what the reader is feeling. Single bold link: Get in touch with Studio Lou here linking to https://www.studiolouinteriors.com/contact. Do not default to curious. Pattern: acknowledge what reader is feeling, explain how Studio Lou is built for that gap, name one specific thing Studio Lou does, close with link."},
    {"id": "blog-5", "category": "blog", "text": "Studio Lou linking rules: Internal links maximum 3 per post, deploy near end of body or in conclusion not intro. Outbound citations target 3 or more per post mixing institutional and trade press. Institutional sources: Steelcase, BLS, Stanford, Harvard Business Review, Buffer State of Remote Work. Trade press: Apartment Therapy, Dwell, Livingetc, Domino, Sight Unseen, WWD, Business of Home."},
    {"id": "blog-6", "category": "blog", "text": "Studio Lou blog formatting: Default format is prose paragraphs, no bullets unless structure is genuinely list-shaped. Bold lead-ins for parallel entities within a prose section. No H3 subheadings inside major sections unless they need their own keyword targeting. No em dashes anywhere. Smart quotes throughout. Concrete details over abstractions."},
    {"id": "blog-7", "category": "blog", "text": "Pinterest pin description three-part formula: 1. Keyword phrase up front targeting Pinterest search algorithm. 2. Credibility marker positioning Studio Lou as authority. 3. Click hook giving reader a reason to tap through. Example: Home office lighting ideas for productivity, most remote workers get this wrong. Studio Lou breaks down the lighting setup that actually improves focus. Full guide on the blog."},
    {"id": "persona-1", "category": "persona", "text": "Studio Lou primary audience: design-curious homeowners who want a designed space without hiring a traditional full-service firm. DIY-adjacent, budget-conscious to mid-range. Find Studio Lou primarily through Pinterest and Instagram. Respond to content that gives genuine insight from a real designer who lives in a real space. Primary audience for home office content, e-design services, and lifestyle-adjacent posts."},
    {"id": "persona-2", "category": "persona", "text": "Studio Lou secondary audience: solo or small interior design firms who are strong on design execution but under-resourced on marketing. Looking for strategy, systems, and specific tactics, not generic business advice. Most active during Month 3 Marketing for Designers content. Find Studio Lou through LinkedIn, blog search, and design industry channels."},
    {"id": "persona-3", "category": "persona", "text": "Studio Lou hidden tertiary audience: hiring managers at home and lifestyle DTC brands including Lulu and Georgia, Minted, Thrive Market. This audience is NEVER addressed directly in content and never named in posts. It is a structural layer only. The Studio Lou blog reads as a marketing case study in aggregate."},
    {"id": "persona-4", "category": "persona", "text": "Studio Lou fourth audience: business owners and startup founders who care about how design decisions affect work performance, client perception, and productivity. Primary audience for Month 4 Startup and Modern Office Design. Respond to ROI framing and content that bridges aesthetic decisions with business outcomes."},
    {"id": "archive-1", "category": "archive", "text": "Lauren and Gavin share a home office, both desks on the same wall. Lauren setup: Uplift standing desk, monitor and laptop on dual-monitor stand, lighter residential chair not an Aeron, Article console, filing cabinet, wall shelving, linen pinboard. Gavin setup: wider Uplift standing desk, Herman Miller chair, single BenQ monitor with built-in KVM switch, Mac mini, custom PC to the left, laptop and iPad tucked away, dry-erase board, steel pegboard. Always refer to Gavin as Lauren's boyfriend in blog body copy, never partner."},
    {"id": "archive-2", "category": "archive", "text": "Gavin works remotely in growth marketing at HelloData, a B2B multifamily SaaS company, approximately two years at current company. Day includes 7am all-hands, internal training calls, monitoring and optimizing HubSpot campaigns and ad campaigns. Previously approximately 6 sales calls per day, now less customer-facing. Does NOT do extensive async Slack or docs writing. Always refer to him as Lauren's boyfriend, never partner."},
    {"id": "archive-3", "category": "archive", "text": "Month 1 AI x Interior Design: four blogs covering AI tools for interior design tested comparison of 8 tools, real design workflows using AI, AI marketing stack for design firms, AI limits in design. Month 1 established sprint week system, carousel template library, visual brand system, all platform posting conventions."},
    {"id": "archive-4", "category": "archive", "text": "Month 2 Home Office Design: four blogs covering shared home office layouts for two-worker households written from Lauren and Gavin real setup, the startup remote worker setup, creative work home offices, home office mistakes. Strongest-performing content month. Content operations reference document built during Month 2."},
    {"id": "archive-5", "category": "archive", "text": "Month 3 Marketing for Designers: four blogs covering positioning strategy for design firms, content systems for design practices, visibility channels for interior designers, discovery and intake. Deployed during active job application and interview phase. Website copy audit completed. Social bios rewritten across all four platforms."},
    {"id": "archive-6", "category": "archive", "text": "Month 4 Startup and Modern Office Design in progress: four blogs covering return-to-office design failures contrarian angle, startup office acoustics spec-level guide, founder-facing budget guide Your First Startup Office, editorial for commercial designers AI in Commercial Interior Design. Weeks 1 and 2 social content produced."},
    {"id": "archive-7", "category": "archive", "text": "Studio Lou technical infrastructure: website built on Framer. TikTok production uses CapCut, desktop upload workaround for Reels compatibility. Blog headers built in Canva papercraft collage aesthetic. Carousel templates built in Canva. Buffer for LinkedIn and TikTok scheduling free tier. Meta Business Suite for Instagram. Pinterest native scheduler. Lauren also sells papercraft-style vector graphics on Gumroad and Etsy."},
]

if __name__ == "__main__":
    print("Setting up Studio Lou RAG...")
    index = setup_index()
    index_chunks(index, CHUNKS)
    print("\nStudio Lou knowledge base is live in Pinecone!")