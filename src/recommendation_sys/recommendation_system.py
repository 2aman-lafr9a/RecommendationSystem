import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import precision_score, recall_score, f1_score, mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))

# Get the project root directory
project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
sys.path.append(project_root)

from connection.database_connection import connect_to_database, extract_ratings_data, extract_insurances_data, close_connection


script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Construct the file path using os.path.join
file_path = os.path.join(script_dir, "../../data/trained/clustered_players.csv")
df_players = pd.read_csv(file_path)

def recommendation_system(player_data):
    # Set the working directory to the location of your script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # Load clustered players data
    file_path = os.path.join(script_dir, "../../data/trained/clustered_players.csv")
    df_players = pd.read_csv(file_path)

    # print(df_players.head())

    # Load scaler and kmeans model
    scaler = pd.read_pickle("../model/scaler_model.pkl")
    kmeans = pd.read_pickle("../model/kmeans_model.pkl")

     # Connect to the PostgreSQL databases with different ports
    ratings_conn = connect_to_database('aman.francecentral.cloudapp.azure.com', 5433, 'postgres', 'postgres', 'rating_management')
    #!! insurances_conn = connect_to_database('aman.francecentral.cloudapp.azure.com', 5432, 'postgres', 'postgres', 'agency_offers_database')

    # Extract data from the ratings and insurances tables
    df_ratings = extract_ratings_data(ratings_conn)
    #!! df_insurances = extract_insurances_data(insurances_conn)


    print("---------------df_ratings----------")
    print(df_ratings)
    print("---------------df_ratings----------")

    # Classify and add new user
    df_players = classify_and_add_user(pd.DataFrame([player_data]), df_players, kmeans, scaler)

    # Generate insurance data
    insurances_data = {
        'name': ['Insurance A', 'Insurance B', 'Insurance C', 'Insurance D', 'Insurance E', 'Insurance F', 'Insurance J'],
        'type': ['Normal', 'Premium', 'Deluxe', 'Ultimate', 'Normal', 'Ultimate', 'Ultimate'],
        'description': ['Description A', 'Description B', 'Description C', 'Description D', 'Description E', 'Description F', 'Description J'],
        'price': np.random.randint(1000, 10000, size=7),
        'date': [datetime.now() - timedelta(days=i) for i in range(7)]
    }

    df_insurances = pd.DataFrame(insurances_data)
    df_insurances['insuranceId'] = range(1, len(df_insurances) + 1)

    # User-item collaborative filtering
    player_id = player_data['playerId']
    cluster_insurances = insurance_of_cluster_players(player_id, df_players, df_insurances)

    # Check if the extracted data is sufficient
    if len(df_ratings) < 10:
        # Generate fake data in casee if the getting rating data from database is fake 
        ratings_data = generate_ratings_data(player_id, cluster_insurances, df_players)
    

    df_ratings = pd.DataFrame(ratings_data)

    # Check if the player_id already exists in df_ratings
    existing_player_rows = df_ratings[df_ratings['playerId'] == player_id]

    # Check if there are no rows for the player_id
    if len(existing_player_rows) == 0:
        # Choose 5 random insurances from the cluster
        num_insurance_choices = min(3, len(cluster_insurances))
        selected_insurances = np.random.choice(cluster_insurances['insuranceId'], size=num_insurance_choices, replace=False)

        # Generate random ratings between 1 and 5 for the new player
        new_player_ratings = {
            'playerId': np.full(num_insurance_choices, player_id),
            'insuranceId': selected_insurances.tolist(),
            'rating': np.random.randint(1, 6, size=num_insurance_choices),
            'timestamp': np.full(num_insurance_choices, datetime.now()).tolist()
        }

        new_player_ratings_df = pd.DataFrame(new_player_ratings)

        # Append the new player's ratings to the existing df_ratings
        df_ratings = pd.concat([df_ratings, new_player_ratings_df], ignore_index=True)

    print(df_ratings[df_ratings['playerId'] == player_id])
    print("--------------------")


    # Create the user-item matrix
    user_item_matrix = pd.pivot_table(df_ratings, values='rating', index='playerId', columns='insuranceId', fill_value=0)
    print(user_item_matrix[user_item_matrix.index == player_id])
    # Fit NearestNeighbors
    nn_model = NearestNeighbors(metric='cosine', algorithm='brute')
    nn_model.fit(user_item_matrix)

    # User-to-User Collaborative Filtering
    predictions = user_to_user_predictions(player_id, df_ratings, user_item_matrix, nn_model)
    top_recommendations = top_k_recommendations(predictions, k=10)

    if not top_recommendations:
        cluster_insurance_ratings = df_ratings[df_ratings['insuranceId'].isin(cluster_insurances['insuranceId'])]

        sorted_cluster_insurance_ratings = cluster_insurance_ratings.sort_values(by='rating', ascending=False)

        selected_insurance_ids = sorted_cluster_insurance_ratings['insuranceId'].unique()[:3]

        top_recommendations = sorted(selected_insurance_ids, key=lambda x: sorted_cluster_insurance_ratings[sorted_cluster_insurance_ratings['insuranceId'] == x]['rating'].iloc[0], reverse=True)


    # Export predictions to CSV
    predictions_df = pd.DataFrame(list(predictions.items()), columns=['Insurance', 'Predicted_Rating'])
    csv_filename = f'../../data/recommended/predictions_{player_id}.csv'
    predictions_df.to_csv(csv_filename, index=False)

    return top_recommendations, csv_filename


def classify_and_add_user(new_user_df, players_df, kmeans_model, scaler_model):
    if players_df.empty:
        new_user_df['Cluster_Labels'] = 0
        players_df = pd.concat([players_df, new_user_df], ignore_index=True)
    else:
        existing_user = players_df[players_df['Name'] == new_user_df['Name'].iloc[0]]
        if not existing_user.empty:
            print(f"User '{new_user_df['Name'].iloc[0]}' already exists in the dataset.")
        else:
            new_user_std = scaler_model.transform(new_user_df[['Value(£)', 'Overall']])
            cluster_label = kmeans_model.predict(new_user_std)[0]
            new_user_df['Cluster_Labels'] = cluster_label
            players_df = pd.concat([players_df, new_user_df], ignore_index=True)

    return players_df


def insurance_of_cluster_players(player_id, df_players, df_insurances):
    player_cluster = df_players.loc[df_players['playerId'] == player_id, 'Cluster_Labels'].values[0]
    cluster_type_mapping = {0: 'Normal', 1: 'Premium', 2: 'Deluxe', 3: 'Ultimate'}
    player_insurance_type = cluster_type_mapping.get(player_cluster)
    recommended_insurances = df_insurances[df_insurances['type'] == player_insurance_type]

    return recommended_insurances


def generate_ratings_data(player_id, cluster_insurances, df_players):
    
    print("player_id", player_id)
    print(cluster_insurances)
    print(df_players)
    player_cluster = df_players.loc[df_players['playerId'] == player_id, 'Cluster_Labels'].values[0]
    similar_players = df_players[df_players['Cluster_Labels'] == player_cluster]

    ratings_data = {
        'playerId': np.random.choice(similar_players.playerId, size=200),
        'insuranceId': np.random.choice(cluster_insurances.insuranceId, size=200),
        'rating': np.random.randint(1, 6, size=200),
        'timestamp': [datetime.now() - timedelta(days=i) for i in range(200)]
    }

    return ratings_data

def find_candidate_items(player_id, neighbors_model, user_item_matrix, df_ratings):
    # Check if the player exists in the dataset

    if player_id not in df_ratings['playerId'].unique():
        print(f"Player with ID {player_id} not found.")
        return []

    # Map the player ID to the corresponding index in user_item_matrix
    player_indices = user_item_matrix.index.get_indexer_for([player_id])

    # Query for neighbors
    _, neighbor_indices = neighbors_model.kneighbors([user_item_matrix.iloc[player_indices[0]]], n_neighbors=20)

    # Flatten the array of neighbor indices
    neighbor_indices = neighbor_indices.flatten()

    # Filter ratings for similar users
    similar_users_ratings = df_ratings[df_ratings.index.isin(neighbor_indices)]

    # Sort items in decreasing order of frequency
    frequency = similar_users_ratings.groupby('insuranceId')['rating'].count().reset_index(name='count').sort_values(['count'], ascending=False)
    candidate_items = frequency['insuranceId'].tolist()

    # Exclude items already rated by the active player
    active_player_ratings = df_ratings[df_ratings['playerId'] == player_id]['insuranceId'].tolist()
    candidate_items = [item for item in candidate_items if item not in active_player_ratings]

    # Return the top 5 candidate items
    return candidate_items[:]


def predict_ratings(active_player_index, user_item_matrix, cosine_sim, candidates):
    # Get the similarity scores for all players
    sim_scores = list(enumerate(cosine_sim[active_player_index]))

    # Sort the players based on similarity scores
    sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)

    # Get the indices of similar players
    similar_players_indices = [x[0] for x in sim_scores]

    # Get the ratings of the active player
    active_player_ratings = user_item_matrix.iloc[active_player_index]

    # Initialize a dictionary to store predicted ratings and total similarity scores
    predicted_ratings = {}
    total_similarity_scores = {}

    # Iterate over similar players and predict ratings
    for player_index in similar_players_indices:
        if player_index == active_player_index:
            continue  # Skip the active player

        # Get the ratings of the similar player
        similar_player_ratings = user_item_matrix.iloc[player_index]

        # Find items rated by the similar player that are in the candidate list
        candidate_items = set(similar_player_ratings[candidates].index)

        # Predict ratings for candidate items
        for item in candidate_items:
            if item not in predicted_ratings:
                predicted_ratings[item] = 0
                total_similarity_scores[item] = 0

            # Use the similarity score to predict the rating
            predicted_ratings[item] += sim_scores[player_index][1] * similar_player_ratings[item]
            total_similarity_scores[item] += sim_scores[player_index][1]

    # Normalize the predicted ratings between 1 and 5
    for item in predicted_ratings:
        if total_similarity_scores[item] != 0:
            predicted_ratings[item] /= total_similarity_scores[item]
            # Ensure the rating is between 1 and 5
            predicted_ratings[item] = min(5, max(1, predicted_ratings[item]))

    # Sort the predicted ratings in descending order
    predicted_ratings = dict(sorted(predicted_ratings.items(), key=lambda x: x[1], reverse=True))

    return predicted_ratings


def user_to_user_predictions(active_player_id, df_ratings, user_item_matrix, nn_model):
    cosine_sim = cosine_similarity(user_item_matrix)

    if active_player_id not in df_ratings['playerId'].unique():
        print(f"Player with ID {active_player_id} not found.")
        return {}

    active_player_indices = user_item_matrix.index.get_indexer_for([active_player_id])
    if not active_player_indices or active_player_indices[0] == -1:
        print(f"Active player with ID {active_player_id} not found in user_item_matrix.")
        return {}

    active_player_index = active_player_indices[0]

    candidates = find_candidate_items(active_player_id, nn_model, user_item_matrix, df_ratings)
    print("-------Candidats-------")
    print(candidates)
    print("-------Candidats-------")

    if cosine_sim.shape[0] <= active_player_index:
        return {}

    predicted_ratings = predict_ratings(active_player_index, user_item_matrix, cosine_sim, candidates)

    return predicted_ratings


def top_k_recommendations(predicted_ratings, k=5):
    top_recommendations = list(predicted_ratings.keys())[:k]
    return top_recommendations


##** Here just for testing 

# Example Usage:
new_player_data = {
    'Name': 'New Player',
    'Age': 25,
    'Overall': 80,
    'Value(£)': 4000000,
    'playerId': len(df_players) + 1
}

top_recommendations, csv_filename = recommendation_system(new_player_data)
print("Top Recommendations:", top_recommendations)
print(f"Predictions exported to {csv_filename}")
