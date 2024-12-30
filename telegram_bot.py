
# Replace with your Telegram bot token



import os
import pandas as pd
import re
import logging
from betting_functions import get_game_ev_bets, get_player_ev_bets
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Betting functions
def extract_team_name(bet_name):
    if isinstance(bet_name, str):
        return re.split(r'[+-]', bet_name, 1)[0].strip()
    return None

def squeeze_spreads_with_team_check(spread_df):
    spread_df.loc[:, "line"] = pd.to_numeric(spread_df["line"], errors="coerce")
    positive_spreads = spread_df[
        spread_df["Bet Name"].str.contains("\+", na=False)
    ][["Game ID", "Market Name", "line", "Bet Name", "Sportsbook", "Odds"]].rename(
        columns={"Bet Name": "Bet Name_A", "Odds": "Odds_A"}
    )
    negative_spreads = spread_df[
        spread_df["Bet Name"].str.contains("-", na=False)
    ][["Game ID", "Market Name", "line", "Bet Name", "Sportsbook", "Odds"]].rename(
        columns={"Bet Name": "Bet Name_B", "Odds": "Odds_B"}
    )
    positive_spreads["abs_line"] = positive_spreads["line"].abs()
    negative_spreads["abs_line"] = negative_spreads["line"].abs()
    paired_spreads = pd.merge(
        positive_spreads,
        negative_spreads,
        on=["Game ID", "Market Name", "abs_line", "Sportsbook"],
        suffixes=("_A", "_B"),
        how="outer"
    )
    paired_spreads["Team_positive"] = paired_spreads["Bet Name_A"].apply(extract_team_name)
    paired_spreads["Team_negative"] = paired_spreads["Bet Name_B"].apply(extract_team_name)
    paired_spreads = paired_spreads[
        paired_spreads["Team_positive"] != paired_spreads["Team_negative"]
    ]
    return paired_spreads.drop(columns=["abs_line", "Team_positive", "Team_negative"])

def process_player_props(player_props_df):
    over_bets = player_props_df[
        player_props_df["Bet Name"].str.contains("Over", na=False)
    ]
    under_bets = player_props_df[
        player_props_df["Bet Name"].str.contains("Under", na=False)
    ]
    paired_player_props = pd.merge(
        over_bets,
        under_bets,
        on=["Game ID", "Game Name", "Market Name", "line", "Player Name", "Sportsbook"],
        suffixes=("_A", "_B")
    )
    return paired_player_props

def process_totals(totals_df):
    over_bets = totals_df[
        totals_df["Bet Name"].str.contains("Over", na=False)
    ]
    under_bets = totals_df[
        totals_df["Bet Name"].str.contains("Under", na=False)
    ]
    paired_totals = pd.merge(
        over_bets,
        under_bets,
        on=["Game ID", "Game Name", "Market Name", "line", "Sportsbook"],
        suffixes=("_A", "_B")
    )
    return paired_totals

def combine_processed_data(paired_totals, paired_spreads, props):
    return pd.concat([paired_totals, paired_spreads, props], ignore_index=True, sort=False)

def implied_probability(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)

def calculate_no_vig(row, sharp_book):
    prob_a = implied_probability(row[('Odds_A', sharp_book)])
    prob_b = implied_probability(row[('Odds_B', sharp_book)])
    total_prob = prob_a + prob_b
    no_vig_prob_a = prob_a / total_prob
    no_vig_prob_b = prob_b / total_prob
    return pd.Series([no_vig_prob_a, no_vig_prob_b])
# Initialize column variables

def generate_simple_bet_recommendations(df, user_sportsbook, user_sharpBook):
    """
    Generate simple recommendations for positive EV bets, sorted by EV in descending order.
    """
    df.columns = ['_'.join(col).strip() if isinstance(col, tuple) else col for col in df.columns]
    # Dynamic column naming for sportsbook and sharp book
    sportsbook_column_A = f'Odds_A_{user_sportsbook}'
    sportsbook_column_B = f'Odds_B_{user_sportsbook}'
    sharpBook_column_A = f'Odds_A_{user_sharpBook}'
    sharpBook_column_B = f'Odds_B_{user_sharpBook}'

    # Check books column names (assuming fixed column names for these books)
    checkBook_column_A = 'Odds_A_BetOnline'
    checkBook_column_B = 'Odds_B_BetOnline'
    checkBook2_column_A = 'Odds_A_DraftKings'
    checkBook2_column_B = 'Odds_B_DraftKings'
    checkBook3_column_A = 'Odds_A_BookMaker'
    checkBook3_column_B = 'Odds_B_BookMaker'
    checkBook4_column_A = 'Odds_A_Pinnacle'
    checkBook4_column_B = 'Odds_B_Pinnacle'

    df['EV_A'] = (df['No_Vig_Prob_A_'] - df[f'{user_sportsbook}_Implied_Prob_A_']) * 100
    df['EV_B'] = (df['No_Vig_Prob_B_'] - df[f'{user_sportsbook}_Implied_Prob_B_']) * 100

    # Create a long-form DataFrame for sorting by EV
    recommendations_df = []
    for _, row in df.iterrows():
        if row['EV_A'] > 0:
            recommendations_df.append({
                'Game Name': row['Game Name_'],
                'Bet Name': row['Bet Name_A_'],
                'Market Name': row['Market Name_'],
                f'Sportsbook Odds': row[sportsbook_column_A],
                f'sharpBook Odds': row[sharpBook_column_A],
                'BetOnline Odds': row[checkBook_column_A],
                'DraftKings Odds': row[checkBook2_column_A],
                'BookMaker Odds': row[checkBook3_column_A],
                'Pinnacle Odds': row[checkBook4_column_A],
                'EV': row['EV_A']
            })
        if row['EV_B'] > 0:
            recommendations_df.append({
                'Game Name': row['Game Name_'],
                'Bet Name': row['Bet Name_B_'],
                'Market Name': row['Market Name_'],
                f'Sportsbook Odds': row[sportsbook_column_B],
                f'sharpBook Odds': row[sharpBook_column_B],
                'BetOnline Odds': row[checkBook_column_B],
                'DraftKings Odds': row[checkBook2_column_B],
                'BookMaker Odds': row[checkBook3_column_B],
                'Pinnacle Odds': row[checkBook4_column_B],
                'EV': row['EV_B']
            })

    # Convert recommendations to DataFrame for sorting
    recommendations_df = pd.DataFrame(recommendations_df)
    recommendations_df.sort_values(by='EV', ascending=False, inplace=True)

    # Generate text recommendations
    recommendations = []
    for _, rec in recommendations_df.iterrows():
        recommendations.append(
            f"{rec['Game Name']}\n"
            f"{rec['Bet Name']}\n"
            f"{rec['Market Name']}\n"
            f"{user_sportsbook} Odds: {rec['Sportsbook Odds']}\n"
            f"{user_sharpBook} Odds: {rec['sharpBook Odds']}\n"
            f"BetOnline Odds: {rec['BetOnline Odds']}\n"
            f"DraftKings Odds: {rec['DraftKings Odds']}\n"
            #f"BookMaker Odds: {rec['BookMaker Odds']}\n"
            f"Pinnacle Odds: {rec['Pinnacle Odds']}\n"
            f"EV: {rec['EV']:.2f}%\n"
        )

    return "\n".join(recommendations)  # Join recommendations with actual newlines
async def ev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 4:  # Require at least 4 arguments
        await update.message.reply_text("Usage: /ev sport league sharpBook sportsbook")
        return

    # Fixed arguments
    user_sport = args[0]  # First argument
    user_league = args[1]  # Second argument

    # Flexible parsing for sharpBook and sportsbook
    user_sharpBook = " ".join(args[2:-1])  # Everything between sport/league and sportsbook
    user_sportsbook = args[-1]  # Last argument is always sportsbook

    try:
        # Fetch data
        gdf = get_game_ev_bets(
            api_key=os.getenv('API_KEY'),
            sport=user_sport,
            league=user_league,
            sportsbook=user_sportsbook,
            is_live='false'
        )
        pdf = get_player_ev_bets(
            api_key=os.getenv('API_KEY'),
            sport=user_sport,
            league=user_league,
            sportsbook=user_sportsbook,
            is_live='false'
        )

        # Process and combine data
        paired_spreads = squeeze_spreads_with_team_check(gdf[gdf['Market Name'].str.contains('Point Spread|Puck Line')])
        paired_totals = process_totals(gdf[gdf['Market Name'].str.contains('Total')])
        paired_player_props = process_player_props(pdf)
        final_df = combine_processed_data(paired_totals, paired_spreads, paired_player_props)

        # Pivot and filter
        pivot_df = final_df.pivot_table(
            index=['Game ID', "Game Name", 'Market Name', 'line', "Bet Name_A", 'Bet Name_B'],
            columns='Sportsbook',
            values=['Odds_A', 'Odds_B'],
            aggfunc='mean'
        ).reset_index()

        pivot_df.dropna(subset=[('Odds_A', user_sharpBook), ('Odds_B', user_sharpBook)], inplace=True)
        pivot_df[['No_Vig_Prob_A', 'No_Vig_Prob_B']] = pivot_df.apply(lambda row: calculate_no_vig(row, user_sharpBook), axis=1)
        pivot_df[f'{user_sportsbook}_Implied_Prob_A'] = pivot_df[('Odds_A', user_sportsbook)].apply(implied_probability)
        pivot_df[f'{user_sportsbook}_Implied_Prob_B'] = pivot_df[('Odds_B', user_sportsbook)].apply(implied_probability)
        pivot_df['Is_Positive_EV_A'] = pivot_df['No_Vig_Prob_A'] > pivot_df[f'{user_sportsbook}_Implied_Prob_A']
        pivot_df['Is_Positive_EV_B'] = pivot_df['No_Vig_Prob_B'] > pivot_df[f'{user_sportsbook}_Implied_Prob_B']
        positive_ev_bets = pivot_df[(pivot_df['Is_Positive_EV_A']) | (pivot_df['Is_Positive_EV_B'])]
        positive_ev_bets.to_csv('telegram_bot_evbets.csv', index=False)

        # Generate recommendations
        recommendations = generate_simple_bet_recommendations(positive_ev_bets, user_sportsbook, user_sharpBook)
        if recommendations:
            await update.message.reply_text(f"Here are your +EV bets:\n\n{recommendations}")
        else:
            await update.message.reply_text("No positive EV bets found.")

    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text("An error occurred. Please try again.")
# Bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the Betting Bot! Use /ev to calculate bets.")


def main():
    application = Application.builder().token("7782271846:AAG2pDKDC5enMY8Vm0lhYklgyk026NjMa3U").build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ev", ev))
    application.run_polling()

if __name__ == "__main__":
    main()
