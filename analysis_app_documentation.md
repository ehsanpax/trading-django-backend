# Analysis App Documentation

This document provides an overview of the `analysis` app, how it works, and how to use it to create new analyses.

## Overview

The `analysis` app is a powerful tool for performing various types of analysis on financial instruments. It is designed as a RESTful API that allows users to submit analysis jobs, monitor their status, and retrieve the results. The app is built on a modular architecture that makes it easy to extend with new analysis types.

## How it Works

The analysis process is orchestrated by a set of Celery tasks that run asynchronously. Here's a step-by-step breakdown of the workflow:

1.  **Instrument Management**: Before an analysis can be performed, the instrument must be added to the system. This is done via the `/api/analysis/instruments/` endpoint. When a new instrument is added, a Celery task is triggered to download its historical M1 data from the OANDA API and store it in Parquet files.

2.  **Submitting an Analysis Job**: To start an analysis, a user submits a POST request to the `/api/analysis/submit/` endpoint. The request must include the instrument symbol, the type of analysis to perform, the target timeframe, the date range, and a list of indicator configurations.

3.  **Asynchronous Processing**: When an analysis job is submitted, a Celery task (`run_analysis_job_task`) is triggered to perform the analysis. This task performs the following steps:
    *   Loads the required M1 data from the Parquet files.
    *   Resamples the data to the target timeframe.
    *   Calculates technical indicators dynamically based on the `indicator_configs` provided in the request.
    *   Dynamically imports and runs the appropriate analysis module from the `analysis/core_analysis/` directory.

4.  **Storing and Retrieving Results**: Once the analysis is complete, the results are stored in the `AnalysisResult` model. The user can then retrieve the results by making a GET request to the `/api/analysis/results/{job_id}/` endpoint.

## Available Analyses Endpoint

To get a list of available analysis types, the frontend can make a GET request to `/api/analysis/types/`. This will return a list of all registered analysis types.

## Creating a New Analysis

To create a new analysis, you need to follow these steps:

1.  **Define the Analysis Logic**: Create a new Python module in the `analysis/core_analysis/` directory. This module must contain a `run_analysis` function that takes a Pandas DataFrame with resampled data and indicators as input, along with any parameters for the analysis. The function should return a dictionary containing the analysis results.

2.  **Add the Analysis Type**: Add a new choice to the `ANALYSIS_TYPE_CHOICES` in the `AnalysisJob` model in `analysis/models.py`.

3.  **Map the Analysis Type to the Module**: Add a new entry to the `ANALYSIS_MODULE_MAPPING` in `analysis/tasks.py` to map the new analysis type to the corresponding module.

### Example: Creating an "ATR Squeeze Breakout" Analysis

1.  **Create the analysis module**: Create a new file named `analysis/core_analysis/atr_squeeze_breakout.py` with the analysis logic.

2.  **Update the `AnalysisJob` model**: In `analysis/models.py`, add the new analysis type:

    ```python
    class AnalysisJob(models.Model):
        ANALYSIS_TYPE_CHOICES = [
            ('TREND_CONTINUATION', 'Trend Continuation'),
            ('VWAP_CONDITIONAL', 'VWAP Conditional'),
            ('ATR_SCENARIO', 'ATR Scenario'),
            ('ATR_SQUEEZE_BREAKOUT', 'ATR Squeeze Breakout'), # Add this line
        ]
        # ...
    ```

3.  **Update the `ANALYSIS_MODULE_MAPPING`**: In `analysis/tasks.py`, add the new mapping:

    ```python
    ANALYSIS_MODULE_MAPPING = {
        'TREND_CONTINUATION': 'trend_continuation',
        'VWAP_CONDITIONAL': 'vwap_conditional',
        'ATR_SCENARIO': 'atr_scenario',
        'ATR_SQUEEZE_BREAKOUT': 'atr_squeeze_breakout', # Add this line
    }
    ```

After these changes, and restarting the server, you can submit analysis jobs with the `analysis_type` set to `ATR_SQUEEZE_BREAKOUT`.
