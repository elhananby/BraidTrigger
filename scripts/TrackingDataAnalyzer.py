import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter, find_peaks
from typing import Union, List
from matplotlib.animation import FuncAnimation
from scipy.spatial.distance import directed_hausdorff
from joblib import Parallel, delayed


class TrackingDataAnalyzer:
    def __init__(self, data_source):
        if isinstance(data_source, pd.DataFrame):
            self.df = data_source.copy()
        elif isinstance(data_source, str):
            self.df = pd.read_csv(data_source)
        else:
            raise ValueError("Input must be a pandas DataFrame or a file path")

        self.original_df = self.df.copy()

    def filter_by_time(self, threshold):
        """Filter out objects with total time less than the threshold."""
        time_per_obj = self.df.groupby("obj_id")["timestamp"].agg(["min", "max"])
        time_per_obj["total_time"] = time_per_obj["max"] - time_per_obj["min"]
        valid_objs = time_per_obj[time_per_obj["total_time"] >= threshold].index
        self.df = self.df[self.df["obj_id"].isin(valid_objs)]
        return self

    def filter_by_distance(self, threshold):
        """Filter out objects with total distance traveled less than the threshold."""

        def calculate_distance(group):
            dx = group["x"].diff()
            dy = group["y"].diff()
            dz = group["z"].diff()
            return np.sqrt(dx**2 + dy**2 + dz**2).sum()

        distances = self.df.groupby("obj_id").apply(calculate_distance)
        valid_objs = distances[distances >= threshold].index
        self.df = self.df[self.df["obj_id"].isin(valid_objs)]
        return self

    def calculate_linear_velocity(self):
        """Calculate linear velocity and add it as a new column."""
        self.df["linear_velocity"] = np.sqrt(
            self.df["xvel"] ** 2 + self.df["yvel"] ** 2 + self.df["zvel"] ** 2
        )
        return self

    def calculate_angular_velocity(self):
        """Calculate angular velocity and add it as a new column."""

        def calc_angular_vel(group):
            dx = group["x"].diff()
            dy = group["y"].diff()
            dz = group["z"].diff()
            dt = group["timestamp"].diff()
            r = np.sqrt(group["x"] ** 2 + group["y"] ** 2 + group["z"] ** 2)
            v = np.sqrt(dx**2 + dy**2 + dz**2) / dt
            return v / r

        self.df["angular_velocity"] = (
            self.df.groupby("obj_id")
            .apply(calc_angular_vel)
            .reset_index(level=0, drop=True)
        )
        return self

    def smooth_trajectory(self, window_length=11, polyorder=3):
        """Apply Savitzky-Golay filter to smooth the trajectory."""
        for col in ["x", "y", "z"]:
            self.df[f"{col}_smooth"] = self.df.groupby("obj_id")[col].transform(
                lambda x: savgol_filter(x, window_length, polyorder)
            )
        return self

    def find_peaks(self, column, prominence=1):
        """Find peaks in a specified column."""

        def find_obj_peaks(group):
            peaks, _ = find_peaks(group[column], prominence=prominence)
            return pd.Series(group.iloc[peaks].index, name="peak_indices")

        peak_indices = self.df.groupby("obj_id").apply(find_obj_peaks)
        self.df["is_peak"] = self.df.index.isin(peak_indices.explode())
        return self

    def plot_trajectory(self, obj_id):
        """Plot the trajectory of a specific object."""
        obj_data = self.df[self.df["obj_id"] == obj_id]

        fig, ax = plt.subplots(figsize=(10, 8))
        scatter = ax.scatter(
            obj_data["x"], obj_data["y"], c=obj_data["timestamp"], cmap="viridis"
        )
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_title(f"Trajectory of Object {obj_id}")
        plt.colorbar(scatter, label="Timestamp")
        plt.show()

    def reset(self):
        """Reset the DataFrame to its original state."""
        self.df = self.original_df.copy()
        return self

    def extract_window(
        self,
        idx: int,
        n_before: int = 50,
        n_after: int = 100,
        columns: Union[str, List[str]] = None,
        padding: bool = True,
    ) -> pd.DataFrame:
        """
        Extract a window of data around a specific index from one or more columns.

        Parameters:
        - idx: The central index around which to extract the window.
        - n_before: The number of rows to include before the central index.
        - n_after: The number of rows to include after the central index.
        - columns: The column(s) to extract. If None, all columns are extracted.
                Can be a single column name or a list of column names.
        - padding: If True, pad the extracted window with NaNs to ensure
                it always has length n_before + n_after + 1.

        Returns:
        - A DataFrame containing the extracted window.
        """
        if columns is None:
            columns = self.df.columns
        elif isinstance(columns, str):
            columns = [columns]

        start_idx = max(0, idx - n_before)
        end_idx = min(len(self.df), idx + n_after + 1)

        window = self.df.loc[start_idx:end_idx, columns].copy()

        actual_before = idx - start_idx
        actual_after = end_idx - idx - 1

        window["relative_position"] = range(-actual_before, actual_after + 1)

        if padding and (len(window) < n_before + n_after + 1):
            pad_df = pd.DataFrame(
                np.nan, index=range(n_before + n_after + 1), columns=window.columns
            )
            pad_before = n_before - actual_before
            pad_df.iloc[pad_before : pad_before + len(window)] = window.values
            pad_df["relative_position"] = range(-n_before, n_after + 1)
            window = pad_df

        return window

    def animate_trajectory(self, obj_id, interval=50):
        """
        Create an animated plot of the trajectory for a specific object.

        Parameters:
        - obj_id: The ID of the object to animate.
        - interval: Time interval between frames in milliseconds.

        Returns:
        - A matplotlib animation object.
        """
        obj_data = self.df[self.df["obj_id"] == obj_id].sort_values("timestamp")

        fig, ax = plt.subplots()
        ax.set_xlim(obj_data["x"].min(), obj_data["x"].max())
        ax.set_ylim(obj_data["y"].min(), obj_data["y"].max())
        (line,) = ax.plot([], [], lw=2)

        def init():
            line.set_data([], [])
            return (line,)

        def animate(i):
            line.set_data(obj_data["x"][:i], obj_data["y"][:i])
            return (line,)

        anim = FuncAnimation(
            fig,
            animate,
            init_func=init,
            frames=len(obj_data),
            interval=interval,
            blit=True,
        )

        return anim

    def generate_trajectory_heatmap(self, resolution=100, edges=[-0.25, 0.25]):
        """
        Generate a heatmap of trajectory density.

        Parameters:
        - resolution: The resolution of the heatmap grid.

        Returns:
        - A tuple containing the heatmap and the figure object.
        """
        x = self.df["x"]
        y = self.df["y"]

        heatmap, xedges, yedges = np.histogram2d(
            x, y, bins=resolution, range=[edges, edges]
        )
        extent = [xedges[0], xedges[-1], yedges[0], yedges[-1]]

        fig, ax = plt.subplots()
        im = ax.imshow(heatmap.T, extent=extent, origin="lower", cmap="hot")
        ax.set_title("Trajectory Density Heatmap")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        plt.colorbar(im, ax=ax, label="Density")

        return heatmap, fig

    def detect_stopping_points(self, speed_threshold=0.1, min_duration=5):
        """
        Detect stopping points in trajectories.

        Parameters:
        - speed_threshold: Speed below which an object is considered stopped.
        - min_duration: Minimum duration (in seconds) to consider a stop.

        Returns:
        - A DataFrame with detected stopping points.
        """
        self.df["speed"] = np.sqrt(
            self.df["xvel"] ** 2 + self.df["yvel"] ** 2 + self.df["zvel"] ** 2
        )
        self.df["is_stopped"] = self.df["speed"] < speed_threshold

        stops = []
        for obj_id, group in self.df.groupby("obj_id"):
            stop_starts = group.index[
                group["is_stopped"] & ~group["is_stopped"].shift(1).fillna(False)
            ]
            stop_ends = group.index[
                group["is_stopped"] & ~group["is_stopped"].shift(-1).fillna(False)
            ]

            for start, end in zip(stop_starts, stop_ends):
                duration = group.loc[end, "timestamp"] - group.loc[start, "timestamp"]
                if duration >= min_duration:
                    stops.append(
                        {
                            "obj_id": obj_id,
                            "start_time": group.loc[start, "timestamp"],
                            "end_time": group.loc[end, "timestamp"],
                            "duration": duration,
                            "x": group.loc[start:end, "x"].mean(),
                            "y": group.loc[start:end, "y"].mean(),
                            "z": group.loc[start:end, "z"].mean(),
                        }
                    )

        return pd.DataFrame(stops)

    def calculate_trajectory_similarity(self, obj_id1, obj_id2):
        """
        Calculate similarity between two trajectories using Hausdorff distance.

        Parameters:
        - obj_id1, obj_id2: IDs of the objects to compare.

        Returns:
        - Hausdorff distance between the two trajectories.
        """
        traj1 = self.df[self.df["obj_id"] == obj_id1][["x", "y", "z"]].values
        traj2 = self.df[self.df["obj_id"] == obj_id2][["x", "y", "z"]].values

        return max(
            directed_hausdorff(traj1, traj2)[0], directed_hausdorff(traj2, traj1)[0]
        )

    def parallel_process(self, func, *args, n_jobs=-1):
        """
        Apply a function in parallel across the dataset.

        Parameters:
        - func: The function to apply.
        - *args: Additional arguments for the function.
        - n_jobs: Number of jobs to run in parallel (-1 for all available cores).

        Returns:
        - Results of the parallel processing.
        """
        return Parallel(n_jobs=n_jobs)(
            delayed(func)(group, *args) for _, group in self.df.groupby("obj_id")
        )


# Example usage
if __name__ == "__main__":
    # Create a sample DataFrame for demonstration
    data = pd.DataFrame(
        {
            "obj_id": np.repeat(range(1, 6), 100),
            "frame": np.tile(range(100), 5),
            "timestamp": np.tile(np.arange(0, 10, 0.1), 5),
            "x": np.random.rand(500) * 100,
            "y": np.random.rand(500) * 100,
            "z": np.random.rand(500) * 10,
            "xvel": np.random.randn(500),
            "yvel": np.random.randn(500),
            "zvel": np.random.randn(500),
        }
    )

    # Initialize the analyzer
    analyzer = TrackingDataAnalyzer(data)

    # Filter trajectories
    analyzer.filter_by_time(5).filter_by_distance(50)

    # Calculate and smooth velocities
    analyzer.calculate_linear_velocity().calculate_angular_velocity().smooth_trajectory()

    # Find peaks in linear velocity
    analyzer.find_peaks("linear_velocity", prominence=0.5)

    # Plot trajectory for object 1
    analyzer.plot_trajectory(1)

    # Extract a window of data
    window = analyzer.extract_window(
        250, n_before=50, n_after=50, columns=["x", "y", "z", "linear_velocity"]
    )
    print("Extracted window:")
    print(window)

    # Generate and display trajectory heatmap
    heatmap, fig = analyzer.generate_trajectory_heatmap()
    plt.show()

    # Detect stopping points
    stopping_points = analyzer.detect_stopping_points()
    print("\nDetected stopping points:")
    print(stopping_points)

    # Calculate similarity between two trajectories
    similarity = analyzer.calculate_trajectory_similarity(1, 2)
    print(f"\nSimilarity between trajectories 1 and 2: {similarity}")

    # Use parallel processing for a custom function
    def custom_analysis(group):
        return group["obj_id"].iloc[0], group["linear_velocity"].mean()

    results = analyzer.parallel_process(custom_analysis)
    print("\nResults of parallel processing (Object ID, Mean Linear Velocity):")
    print(results)

    # Animate trajectory for object 1
    anim = analyzer.animate_trajectory(1)
    plt.show()

    print("\nAnalysis complete!")
